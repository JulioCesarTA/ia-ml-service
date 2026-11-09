"""Copia de los datos del comedor para la app móvil: el celular la guarda y genera los reportes SIN internet.

Cada conjunto sale como columnas + filas (listas), con las fechas como texto AAAA-MM-DD, en el mismo orden que el catálogo.
"""
from datetime import datetime

import pandas as pd

from app.services.reportes import catalogo, fuentes


def _valor(v):
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


def registros(roles: list[str]) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """{dataset: [fila como diccionario]} con los valores ya normalizados, y los conjuntos que fallaron."""
    datos, errores = {}, {}
    for did in catalogo.DATASETS:
        if did not in permitidos(roles):
            continue
        try:
            df = fuentes.cargar(did)
        except Exception as e:
            errores[did] = str(e)[:120]
            continue
        cols = [c["nombre"] for c in catalogo.DATASETS[did]["columnas"]]
        datos[did] = [{c: _valor(r[c]) for c in cols} for r in df.to_dict("records")]
    return datos, errores


def construir(roles: list[str]) -> dict:
    datos, errores = registros(roles)
    out = {}
    for did, filas in datos.items():
        cols = [c["nombre"] for c in catalogo.DATASETS[did]["columnas"]]
        out[did] = {"columnas": cols, "filas": [[r[c] for c in cols] for r in filas]}
    return {"generado": datetime.now().strftime("%Y-%m-%d %H:%M"), "datasets": out, "errores": errores}
