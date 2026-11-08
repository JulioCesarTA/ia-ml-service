"""Temperatura diaria (clima) de Santa Cruz para los modelos.

Con internet se pide a Open-Meteo (histórico reciente + pronóstico) y se guarda en la base local; sin internet se
usa lo último guardado y, si no hay nada, el modelo trabaja sin ese dato (sin inventar valores).
"""
import json
import threading
import time

from app.data import clima_api, repo_config

LAT, LON = -17.78, -63.18
_lock = threading.Lock()
_mem: dict = {"t": 0.0, "datos": None, "proximo": 0.0}


def _guardado() -> dict:
    r = repo_config.leer("clima")
    return json.loads(r) if r else {}


def _guardar(d: dict) -> None:
    repo_config.escribir("clima", json.dumps(d))


def temperaturas() -> dict[str, float]:
    """{'2026-11-06': 27.4, ...}. Se refresca cada 6 horas; si falla la red, reintenta a los 10 minutos."""
    with _lock:
        if _mem["datos"] is not None and (time.time() - _mem["t"] < 6 * 3600 or time.time() < _mem["proximo"]):
            return _mem["datos"]
        try:
            datos = clima_api.temperatura_diaria(LAT, LON)
            viejo = _guardado()
            viejo.update(datos)
            _guardar(viejo)
            _mem.update(t=time.time(), datos=viejo, proximo=0.0)
        except Exception:
            _mem.update(datos=_guardado(), proximo=time.time() + 600)
        return _mem["datos"]


def temperatura(fecha: str) -> float | None:
    return temperaturas().get(fecha)


def disponible() -> bool:
    t = temperaturas()
    return bool(t)
