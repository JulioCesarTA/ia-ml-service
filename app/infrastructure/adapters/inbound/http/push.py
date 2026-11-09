"""Notificaciones push: el teléfono registra su token y el sistema avisa por Firebase (FCM).

El router solo traduce HTTP <-> caso de uso: la validación, los roles permitidos y el acceso a los datos
están en `ServicioPush` y en el dominio.
"""
from fastapi import APIRouter, Header, HTTPException

from app.application.push import ServicioPush
from app.domain.errores import DatoInvalido, NoConfigurado
from app.infrastructure.adapters.inbound.http.autenticacion import identidad_bearer
from app.infrastructure.adapters.inbound.http.esquemas.push import BajaIn, DispositivoIn, PruebaIn


def crear_router(push: ServicioPush) -> APIRouter:
    router = APIRouter()

    @router.post("/dispositivo")
    def registrar_dispositivo(body: DispositivoIn, authorization: str | None = Header(default=None)):
        """Guarda el token de este teléfono para el usuario que inició sesión (los roles salen del token, no del cuerpo)."""
        usuario, roles = identidad_bearer(authorization)
        try:
            return push.registrar_dispositivo(body.token, usuario, roles, body.usuario, body.roles, body.plataforma)
        except DatoInvalido as e:
            raise HTTPException(400, str(e))

    @router.post("/baja")
    def baja_dispositivo(body: BajaIn):
        """Al cerrar sesión: este teléfono deja de recibir avisos de ese usuario."""
        return push.dar_de_baja(body.token)

    @router.post("/prueba")
    def prueba(body: PruebaIn):
        """Manda una notificación de prueba a un usuario o a un rol (para comprobar que todo está conectado)."""
        try:
            return push.prueba(body.usuario, body.roles, body.titulo, body.cuerpo)
        except NoConfigurado as e:
            raise HTTPException(503, str(e))
        except DatoInvalido as e:
            raise HTTPException(400, str(e))

    @router.get("/estado")
    def estado():
        return push.estado()

    return router
