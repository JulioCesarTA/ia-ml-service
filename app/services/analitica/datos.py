"""Datos reales del comedor para los modelos: menús con su cupo y las porciones apartadas (reservas).

Se leen por HTTP del servicio de menús (fuente única, sin tocar sus bases) y se guardan unos segundos
para que el dashboard pueda actualizarse en tiempo real sin saturar al servicio.
"""
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from app.data import comedor_http

TURNOS = ("DESAYUNO", "ALMUERZO", "CENA")
SEMANAS_ATRAS = 12
SEMANAS_ADELANTE = 2

_lock = threading.Lock()
_cache: dict = {"t": 0.0, "filas": [], "ok": False}


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pedir(par: tuple[date, str]) -> list[dict]:
    inicio, turno = par
    try:
        return comedor_http.menus_semana(turno, inicio.isoformat())
    except Exception:
        return []


def filas(ttl: float = 15.0) -> list[dict]:
    """Una fila por (fecha, turno, plato): cupo total y porciones apartadas (suma si hay menús repetidos)."""
    with _lock:
        if time.time() - _cache["t"] < ttl:
            return _cache["filas"]
    inicio = _lunes(date.today()) - timedelta(weeks=SEMANAS_ATRAS)
    pares = [(inicio + timedelta(weeks=i), t) for i in range(SEMANAS_ATRAS + SEMANAS_ADELANTE + 1) for t in TURNOS]
    with ThreadPoolExecutor(8) as ex:
        menus = [m for lista in ex.map(_pedir, pares) for m in lista]
    if not menus:                                   # el servicio no respondió: se conserva lo último que se tenía
        with _lock:
            _cache["ok"] = False
            return _cache["filas"]
    acum: dict[tuple, dict] = defaultdict(lambda: {"cupo": 0, "apartadas": 0})
    vistos = set()
    for m in menus:
        if m["id"] in vistos:
            continue
        vistos.add(m["id"])
        for pid, p in (m.get("porciones") or {}).items():
            a = acum[(m["fecha"], m["turno"], pid)]
            a["cupo"] += p["cupo"]
            a["apartadas"] += p["cupo"] - p["disponibles"]
    out = [{"fecha": f, "turno": t, "platoId": p, **v} for (f, t, p), v in sorted(acum.items())]
    with _lock:
        _cache.update(t=time.time(), filas=out, ok=True)
    return out


def firma() -> str:
    """Cambia cuando cambian los datos: sirve para reentrenar solo cuando hace falta."""
    f = filas()
    return f"{len(f)}:{sum(x['apartadas'] for x in f)}:{sum(x['cupo'] for x in f)}"


def fuente_ok() -> bool:
    return bool(_cache["ok"])
