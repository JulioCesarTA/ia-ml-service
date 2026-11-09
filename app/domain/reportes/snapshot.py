"""Reglas de la copia de datos para la app móvil: qué puede ver cada rol y cómo se escribe cada valor."""
from datetime import datetime

import pandas as pd

from app.domain.reportes import catalogo


def valor(v):
    if v is None or v is pd.NaT or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d") if (v.hour == 0 and v.minute == 0) else v.strftime("%Y-%m-%d %H:%M")
    if hasattr(v, "item"):
        v = v.item()
    return round(v, 2) if isinstance(v, float) else v


def permitidos(roles: list[str]) -> set[str]:
    """Los conjuntos de datos que ese rol puede consultar (SPEC §10: cada quien ve solo lo suyo)."""
    out: set[str] = set()
    for r in roles:
        out |= catalogo.PERMISOS.get(r, set())
    return out
