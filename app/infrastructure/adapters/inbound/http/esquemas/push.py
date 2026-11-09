"""Esquemas de entrada de la API de notificaciones push."""
from pydantic import BaseModel


class DispositivoIn(BaseModel):
    token: str
    usuario: str | None = None
    roles: list[str] = []
    plataforma: str = "android"


class BajaIn(BaseModel):
    token: str


class PruebaIn(BaseModel):
    usuario: str | None = None
    roles: list[str] = []
    titulo: str = "Comedor UAGRM"
    cuerpo: str = "Notificación de prueba: si la ves, el push funciona."
