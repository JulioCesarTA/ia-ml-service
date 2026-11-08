"""Aprendizaje supervisado (regresión): raciones que se pedirán por plato, turno y día.

Se entrena con los datos REALES del comedor (porciones apartadas por plato, turno y día) y se vuelve a entrenar
solo cuando esos datos cambian, así el dashboard siempre refleja la realidad.

Variables: día de la semana, turno, cupo ofrecido, feriado, exámenes, vacaciones, temperatura (clima) y la
popularidad histórica del plato. La calidad se mide con validación cruzada (cada fila se predice sin haberla visto)
y se compara contra el baseline "siempre el promedio": si no lo supera, el panel lo dice.
"""
import math
import threading
from collections import defaultdict
from datetime import date

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import KFold, LeaveOneOut, cross_val_predict

from app.services.analitica import clima, datos
from app.services.analitica.calendario import FERIADOS, PERIODOS_EXAMENES, PERIODOS_VACACIONES

MIN_MUESTRAS = 2000          # registros (fecha × turno × plato) mínimos para entrenar
NOMBRES = ["dia_sem", "turno", "cupo", "feriado", "examenes", "vacacion", "temperatura", "popularidad_plato"]
ETIQUETAS = {"dia_sem": "Día de la semana", "turno": "Turno", "cupo": "Cupo ofrecido", "feriado": "Feriado",
             "examenes": "Período de exámenes", "vacacion": "Vacaciones", "temperatura": "Temperatura",
             "popularidad_plato": "Popularidad del plato"}
TURNO_IDX = {"DESAYUNO": 0, "ALMUERZO": 1, "CENA": 2}

_lock = threading.Lock()
_modelo: dict = {"firma": None, "dato": None}


def _en(f: date, periodos) -> int:
    return int(any(a <= f <= b for a, b in periodos))


def _fila(fecha: str, turno: str, cupo: float, popularidad: float, temp: float | None, temp_defecto: float) -> list[float]:
    f = date.fromisoformat(fecha)
    return [f.weekday(), TURNO_IDX.get(turno, 1), cupo, int(f in FERIADOS), _en(f, PERIODOS_EXAMENES),
            _en(f, PERIODOS_VACACIONES), temp if temp is not None else temp_defecto, popularidad]


def _entrenar() -> dict:
    hoy = date.today().isoformat()
    todas = datos.filas()
    pasadas = [x for x in todas if x["fecha"] <= hoy]
    base = {"muestras": len(pasadas), "minimo": MIN_MUESTRAS, "suficiente": len(pasadas) >= MIN_MUESTRAS,
            "fuenteOk": datos.fuente_ok(), "climaDisponible": clima.disponible(), "ultimaFecha": max((x["fecha"] for x in pasadas), default=None)}
    if not base["suficiente"]:
        return {**base, "modelo": None}

    temps = clima.temperaturas()
    conocidas = [temps[x["fecha"]] for x in pasadas if x["fecha"] in temps]
    temp_defecto = float(np.mean(conocidas)) if conocidas else 24.0

    por_plato: dict[str, list[float]] = defaultdict(list)
    for x in pasadas:
        por_plato[x["platoId"]].append(x["apartadas"])
    global_medio = float(np.mean([x["apartadas"] for x in pasadas]))

    def popularidad(plato: str, excluir: float | None = None) -> float:
        v = list(por_plato.get(plato, []))
        if excluir is not None and excluir in v:
            v.remove(excluir)                    # leave-one-out: la fila a predecir no cuenta en su propia popularidad
        return float(np.mean(v)) if v else global_medio

    X = np.array([_fila(x["fecha"], x["turno"], x["cupo"], popularidad(x["platoId"], x["apartadas"]),
                        temps.get(x["fecha"]), temp_defecto) for x in pasadas], dtype=float)
    y = np.array([x["apartadas"] for x in pasadas], dtype=float)

    # Con pocos datos un bosque pequeño y poco profundo sobreajusta menos; con miles de registros puede ser más profundo
    if len(y) >= 500:
        rf = RandomForestRegressor(n_estimators=150, max_depth=9, min_samples_leaf=5, max_features=0.6, random_state=0, n_jobs=-1)
    else:
        rf = RandomForestRegressor(n_estimators=200, max_depth=3, min_samples_leaf=4, max_features=0.5, random_state=0)
    cv = LeaveOneOut() if len(y) <= 120 else KFold(5, shuffle=True, random_state=0)
    pred_cv = cross_val_predict(rf, X, y, cv=cv)
    mae = float(np.mean(np.abs(pred_cv - y)))
    mae_base = float(np.mean(np.abs(y - y.mean())))
    mae_mediana = float(np.mean(np.abs(y - np.median(y))))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - float(np.sum((y - pred_cv) ** 2)) / ss_tot if ss_tot > 0 else None
    rf.fit(X, y)

    por_dia: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for x, p in zip(pasadas, pred_cv):
        por_dia[x["fecha"]][0] += x["apartadas"]
        por_dia[x["fecha"]][1] += float(p)
    return {
        **base, "modelo": rf, "tempDefecto": temp_defecto, "globalMedio": global_medio, "porPlato": dict(por_plato),
        "metricas": {"mae": round(mae, 2), "maeBase": round(mae_base, 2), "maeMediana": round(mae_mediana, 2),
                     "confiable": bool(mae < min(mae_base, mae_mediana)), "r2": None if r2 is None else round(r2, 3),
                     "mejoraVsBase": round(100 * (mae_base - mae) / mae_base, 1) if mae_base > 0 else None,
                     "validacion": "leave-one-out" if len(y) <= 120 else "5-fold"},
        "importancias": sorted(({"variable": ETIQUETAS[n], "peso": round(float(w), 3)}
                                for n, w in zip(NOMBRES, rf.feature_importances_)), key=lambda d: -d["peso"]),
        "serie": [{"fecha": f, "real": round(v[0]), "predicha": round(v[1], 1)} for f, v in sorted(por_dia.items())],
        "conDemanda": int((y > 0).sum()),
    }


def reentrenar() -> dict:
    """Fuerza un nuevo entrenamiento ahora mismo (sin esperar a que cambien los datos)."""
    with _lock:
        _modelo.update(firma=None, dato=None)
    return estado()


def _obtener() -> dict:
    firma = datos.firma() + f"|{date.today().isoformat()}|{len(clima.temperaturas())}"
    with _lock:
        if _modelo["firma"] != firma:
            _modelo.update(firma=firma, dato=_entrenar())
        return _modelo["dato"]


def _predecir(m: dict, fecha: str, turno: str, plato: str, cupo: float) -> float:
    pop = float(np.mean(m["porPlato"][plato])) if plato in m["porPlato"] else m["globalMedio"]
    x = np.array([_fila(fecha, turno, cupo, pop, clima.temperatura(fecha), m["tempDefecto"])], dtype=float)
    return max(0.0, float(m["modelo"].predict(x)[0]))


def estado() -> dict:
    """Todo lo que muestra el dashboard de predicción (datos y plan de cocina)."""
    m = _obtener()
    pub = {k: v for k, v in m.items() if k in ("muestras", "minimo", "suficiente", "fuenteOk", "climaDisponible", "ultimaFecha")}
    if not m["modelo"]:
        pub["mensaje"] = (f"Se necesitan al menos {MIN_MUESTRAS} registros de menús con reservas para entrenar; "
                          f"hay {m['muestras']}. El modelo se entrenará solo cuando haya más datos.")
        return pub
    hoy = date.today().isoformat()
    plan = []
    for x in datos.filas():
        if x["fecha"] > hoy:
            p = _predecir(m, x["fecha"], x["turno"], x["platoId"], x["cupo"])
            plan.append({"fecha": x["fecha"], "turno": x["turno"], "platoId": x["platoId"], "cupo": x["cupo"],
                         "apartadas": x["apartadas"], "prediccion": round(p, 1), "sugerida": min(int(x["cupo"]), max(0, math.ceil(p * 1.1)))})
    return {**pub, "metricas": m["metricas"], "importancias": m["importancias"], "serie": m["serie"],
            "conDemanda": m["conDemanda"], "plan": plan,
            "platos": sorted({x["platoId"] for x in datos.filas()})}


def predecir(fecha: str, plato_id: str, turno: str = "ALMUERZO", cupo: float | None = None) -> dict:
    m = _obtener()
    f = date.fromisoformat(fecha)
    cupos = [x["cupo"] for x in datos.filas() if x["platoId"] == plato_id] or [x["cupo"] for x in datos.filas()]
    cupo = float(cupo if cupo is not None else (np.mean(cupos) if cupos else 50))
    temp = clima.temperatura(fecha)
    if m["modelo"]:
        raciones = _predecir(m, fecha, turno, plato_id, cupo)
    else:                                          # sin datos suficientes: el promedio real observado (o cero)
        todas = [x["apartadas"] for x in datos.filas() if x["fecha"] <= date.today().isoformat()]
        raciones = float(np.mean(todas)) if todas else 0.0
    return {"racionesEstimadas": max(1, int(round(raciones))), "diaSemana": ["lun", "mar", "mie", "jue", "vie", "sab", "dom"][f.weekday()],
            "esFeriado": f in FERIADOS, "enPeriodoExamenes": bool(_en(f, PERIODOS_EXAMENES)),
            "enVacaciones": bool(_en(f, PERIODOS_VACACIONES)), "temperatura": temp,
            "entrenado": bool(m["modelo"]), "muestras": m["muestras"]}
