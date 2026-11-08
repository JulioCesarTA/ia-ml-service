"""Datos para los reportes de la app móvil (los reportes se generan en el celular, sin internet)."""
from fastapi import APIRouter, Header

from app.services.reportes import snapshot

router = APIRouter()


@router.get("/snapshot")
def get_snapshot(rol: str = "administrador", x_roles: str | None = Header(default=None)):
    """Copia de los datos permitidos para el rol. Con la autenticación activa, el gateway fija x-roles desde el token."""
    roles = [r.strip() for r in (x_roles or rol).split(",") if r.strip()]
    return snapshot.construir(roles)
