"""Esquemas de entrada de la API de modelos de IA."""
from datetime import date

from pydantic import BaseModel


class DemandaIn(BaseModel):
    fecha: date
    plato_id: str
    turno: str = "ALMUERZO"


# ----------------------------- celular: IA local (TensorFlow Lite) + fotos en S3 -----------------------------
class SubidaIn(BaseModel):
    tipo: str                       # ref | bandeja
    cliente_id: str
    fecha: str | None = None


class ReferenciaMovilIn(BaseModel):
    cliente_id: str
    plato_id: str
    fecha: str
    turno: str
    f_ref: float
    comida: list[list[float]]
    fondo: list[list[float]]
    foto_key: str | None = None
    advertencia: str | None = None
    sectores: dict | None = None          # {"zonas": {sector: n}, "nombres": {sector: nombre}}


class BandejaMovilIn(BaseModel):
    cliente_id: str
    ref_id: str
    restante: float
    confianza: float
    foto_key: str | None = None
    sectores: list[dict] | None = None    # [{clase, nombre, restante}]
