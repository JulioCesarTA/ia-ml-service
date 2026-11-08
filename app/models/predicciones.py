"""Esquemas de entrada de la API de modelos de IA."""
from datetime import date

from pydantic import BaseModel


class DemandaIn(BaseModel):
    fecha: date
    plato_id: str
    turno: str = "ALMUERZO"
