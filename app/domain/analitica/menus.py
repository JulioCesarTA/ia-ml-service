"""Cómo se resumen los menús publicados en filas (fecha, turno, plato) con su cupo y porciones apartadas."""
from collections import defaultdict
from datetime import date, timedelta

TURNOS = ("DESAYUNO", "ALMUERZO", "CENA")


def lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def filas_de_menus(menus: list[dict]) -> list[dict]:
    """Una fila por (fecha, turno, plato): cupo total y porciones apartadas (suma si hay menús repetidos)."""
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
    return [{"fecha": f, "turno": t, "platoId": p, **v} for (f, t, p), v in sorted(acum.items())]


def firma(filas: list[dict]) -> str:
    """Cambia cuando cambian los datos: sirve para reentrenar solo cuando hace falta."""
    return f"{len(filas)}:{sum(x['apartadas'] for x in filas)}:{sum(x['cupo'] for x in filas)}"
