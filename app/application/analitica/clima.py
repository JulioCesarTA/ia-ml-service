"""Temperatura diaria (clima) de Santa Cruz para los modelos.

Con internet se pide al puerto ApiClima (histórico reciente + pronóstico) y se guarda en la base local; sin internet
se usa lo último guardado y, si no hay nada, el modelo trabaja sin ese dato (sin inventar valores).
"""
import json
import threading
import time
from datetime import date, timedelta

from app.application.ports.externos import ApiClima
from app.application.ports.repositorios import RepositorioConfig

LAT, LON = -17.78, -63.18


class ServicioClima:
    def __init__(self, api: ApiClima, config: RepositorioConfig):
        self._api = api
        self._config = config
        self._lock = threading.Lock()
        self._mem: dict = {"t": 0.0, "datos": None, "proximo": 0.0, "en_linea": None}

    def _guardado(self) -> dict:
        r = self._config.leer("clima")
        return json.loads(r) if r else {}

    def _guardar(self, d: dict) -> None:
        self._config.escribir("clima", json.dumps(d))

    def temperaturas(self) -> dict[str, float]:
        """{'2026-11-06': 27.4, ...}. Se refresca cada 6 horas; si falla la red, reintenta a los 10 minutos."""
        with self._lock:
            m = self._mem
            if m["datos"] is not None and (time.time() - m["t"] < 6 * 3600 or time.time() < m["proximo"]):
                return m["datos"]
            try:
                datos = self._api.temperatura_diaria(LAT, LON)
                viejo = self._guardado()
                viejo.update(datos)
                self._completar_historial(viejo)
                self._guardar(viejo)
                m.update(t=time.time(), datos=viejo, proximo=0.0, en_linea=True)
            except Exception:
                m.update(datos=self._guardado(), proximo=time.time() + 600, en_linea=False)
            return m["datos"]

    def _completar_historial(self, d: dict) -> None:
        """Con internet, baja del archivo histórico los 3 años anteriores si aún no están guardados."""
        hoy = date.today()
        desde = (hoy - timedelta(days=365 * 3 + 1)).isoformat()
        if d and min(d) <= (hoy - timedelta(days=365 * 3 - 30)).isoformat():
            return
        try:
            d.update(self._api.temperatura_historica(LAT, LON, desde, (hoy - timedelta(days=93)).isoformat()))
        except Exception:
            pass                                           # el clima histórico es un extra: sin él el modelo igual entrena

    def actualizar(self) -> bool:
        """Fuerza una nueva consulta de clima ahora mismo. True si hubo internet; False si se usa lo guardado."""
        with self._lock:
            self._mem.update(t=0.0, datos=None, proximo=0.0)
        self.temperaturas()
        return bool(self._mem["en_linea"])

    def temperatura(self, fecha: str) -> float | None:
        return self.temperaturas().get(fecha)

    def disponible(self) -> bool:
        t = self.temperaturas()
        return bool(t)
