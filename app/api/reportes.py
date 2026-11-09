"""Reportes del comedor. El intérprete de español y el motor corren EN el navegador y en el teléfono (IA local, sin
internet); el servidor solo entrega la copia de datos y el catálogo:

- GET /reportes/snapshot : datos y catálogo que el rol puede consultar (web y app los guardan para trabajar sin conexión)

El motor de Python (services/reportes) es la referencia: con él se genera el archivo de paridad que comprueba que
el motor del navegador y el del teléfono dan exactamente lo mismo (herramientas/generar_paridad_reportes.py).
"""
from fastapi import APIRouter, Header

from app.services.reportes import snapshot

router = APIRouter()


def _roles(rol: str, x_roles: str | None) -> list[str]:
    return [r.strip() for r in (x_roles or rol).split(",") if r.strip()]


@router.get("/snapshot")
def get_snapshot(rol: str = "administrador", x_roles: str | None = Header(default=None)):
    """Copia de los datos permitidos para el rol. Con la autenticación activa, el gateway fija x-roles desde el token."""
    return snapshot.construir(_roles(rol, x_roles))
