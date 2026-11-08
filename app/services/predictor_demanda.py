"""Predicción de demanda con el modelo supervisado entrenado con los datos reales (ver analitica/regresion.py)."""
from datetime import date

from app.services.analitica import regresion


def predecir_demanda(features: dict) -> dict:
    fecha = features.get("fecha") or date.today()
    fecha = fecha.isoformat() if isinstance(fecha, date) else str(fecha)
    return regresion.predecir(fecha, str(features.get("plato_id", "")), features.get("turno", "ALMUERZO"))
