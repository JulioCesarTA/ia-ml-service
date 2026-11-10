"""Predicción de demanda (caso de uso): entrena con los datos REALES del comedor y vuelve a entrenar solo cuando
esos datos cambian, así el dashboard siempre refleja la realidad. El cálculo está en el dominio."""
import math
import threading
from datetime import date

import numpy as np

from app.application.analitica.clima import ServicioClima
from app.application.analitica.datos import DatosMenus
from app.domain.analitica import regresion as dom

MIN_HISTORIAL_PLATO = 10     # registros (días servidos) que necesita un plato para aparecer en el predictor


class ServicioRegresion:
    def __init__(self, datos: DatosMenus, clima: ServicioClima, min_muestras: int = dom.MIN_MUESTRAS):
        self._datos = datos
        self._clima = clima
        self.min_muestras = min_muestras
        self._lock = threading.Lock()
        self._modelo: dict = {"firma": None, "dato": None}

    def _entrenar(self) -> dict:
        hoy = date.today().isoformat()
        todas = self._datos.filas()
        pasadas = [x for x in todas if x["fecha"] <= hoy]
        base = {"muestras": len(pasadas), "minimo": self.min_muestras, "suficiente": len(pasadas) >= self.min_muestras,
                "fuenteOk": self._datos.fuente_ok(), "climaDisponible": self._clima.disponible(),
                "ultimaFecha": max((x["fecha"] for x in pasadas), default=None)}
        if not base["suficiente"]:
            return {**base, "modelo": None}
        return {**base, **dom.entrenar(pasadas, self._clima.temperaturas())}

    def reentrenar(self) -> dict:
        """Fuerza un nuevo entrenamiento ahora mismo (sin esperar a que cambien los datos)."""
        with self._lock:
            self._modelo.update(firma=None, dato=None)
        return self.estado()

    def _obtener(self) -> dict:
        firma = self._datos.firma() + f"|{date.today().isoformat()}|{len(self._clima.temperaturas())}"
        with self._lock:
            if self._modelo["firma"] != firma:
                self._modelo.update(firma=firma, dato=self._entrenar())
            return self._modelo["dato"]

    def _predecir(self, m: dict, fecha: str, turno: str, plato: str, cupo: float) -> float:
        return dom.predecir_valor(m, fecha, turno, plato, cupo, self._clima.temperatura(fecha))

    def estado(self) -> dict:
        """Todo lo que muestra el dashboard de predicción (datos y plan de cocina)."""
        m = self._obtener()
        pub = {k: v for k, v in m.items() if k in ("muestras", "minimo", "suficiente", "fuenteOk", "climaDisponible", "ultimaFecha")}
        if not m["modelo"]:
            pub["mensaje"] = (f"Se necesitan al menos {self.min_muestras} registros de menús con reservas para entrenar; "
                              f"hay {m['muestras']}. El modelo se entrenará solo cuando haya más datos.")
            return pub
        hoy = date.today().isoformat()
        plan = []
        for x in self._datos.filas():
            if x["fecha"] > hoy:
                p = self._predecir(m, x["fecha"], x["turno"], x["platoId"], x["cupo"])
                plan.append({"fecha": x["fecha"], "turno": x["turno"], "platoId": x["platoId"], "cupo": x["cupo"],
                             "apartadas": x["apartadas"], "prediccion": round(p, 1), "sugerida": min(int(x["cupo"]), max(0, math.ceil(p * 1.1)))})
        # Platos para el predictor: solo los que tienen historial suficiente (los de menús de prueba quedan fuera)
        veces: dict[str, int] = {}
        for x in self._datos.filas():
            veces[x["platoId"]] = veces.get(x["platoId"], 0) + 1
        return {**pub, "metricas": m["metricas"], "importancias": m["importancias"], "serie": m["serie"],
                "conDemanda": m["conDemanda"], "plan": plan,
                "platos": sorted(p for p, n in veces.items() if n >= MIN_HISTORIAL_PLATO) or sorted(veces)}

    def predecir(self, fecha: str, plato_id: str, turno: str = "ALMUERZO", cupo: float | None = None) -> dict:
        m = self._obtener()
        info = dom.info_fecha(fecha)
        cupos = [x["cupo"] for x in self._datos.filas() if x["platoId"] == plato_id] or [x["cupo"] for x in self._datos.filas()]
        cupo = float(cupo if cupo is not None else (np.mean(cupos) if cupos else 50))
        temp = self._clima.temperatura(fecha)
        if m["modelo"]:
            raciones = self._predecir(m, fecha, turno, plato_id, cupo)
        else:                                          # sin datos suficientes: el promedio real observado (o cero)
            todas = [x["apartadas"] for x in self._datos.filas() if x["fecha"] <= date.today().isoformat()]
            raciones = float(np.mean(todas)) if todas else 0.0
        return {"racionesEstimadas": max(1, int(round(raciones))), "diaSemana": info["diaSemana"],
                "esFeriado": info["esFeriado"], "enPeriodoExamenes": info["enPeriodoExamenes"],
                "enVacaciones": info["enVacaciones"], "temperatura": temp,
                "entrenado": bool(m["modelo"]), "muestras": m["muestras"]}

    def predecir_demanda(self, features: dict) -> dict:
        """Predicción para los agentes (features: plato_id, fecha, turno)."""
        fecha = features.get("fecha") or date.today()
        fecha = fecha.isoformat() if isinstance(fecha, date) else str(fecha)
        return self.predecir(fecha, str(features.get("plato_id", "")), features.get("turno", "ALMUERZO"))
