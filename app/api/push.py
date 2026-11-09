"""Notificaciones push: el teléfono registra su token y el sistema avisa por Firebase (FCM)."""
import base64
import json

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.data import repo_dispositivos
from app.services import push

router = APIRouter()

ROLES_VALIDOS = {"administrador", "nutricionista", "cocina_almacen", "servicio_caja", "estudiante"}


def _del_token(authorization: str | None) -> tuple[str | None, list[str]]:
    """Usuario y roles que dice el JWT de la petición. Si el gateway valida las firmas (autenticación activa),
    esto es confiable; sin token devuelve (None, [])."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None, []
    try:
        p = authorization.split(" ", 1)[1].split(".")[1]
        datos = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        roles = [r for r in (datos.get("realm_access") or {}).get("roles", []) if r in ROLES_VALIDOS]
        return datos.get("preferred_username"), roles
    except Exception:
        return None, []


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


@router.post("/dispositivo")
def registrar_dispositivo(body: DispositivoIn, authorization: str | None = Header(default=None)):
    """Guarda el token de este teléfono para el usuario que inició sesión (los roles salen del token, no del cuerpo)."""
    if not 20 <= len(body.token) <= 4096:
        raise HTTPException(400, "El token del dispositivo no es válido")
    usuario, roles = _del_token(authorization)
    usuario = usuario or (body.usuario or "").strip()
    roles = roles or [r for r in body.roles if r in ROLES_VALIDOS]
    if not usuario:
        raise HTTPException(400, "Falta el usuario")
    repo_dispositivos.registrar(body.token, usuario, roles, body.plataforma[:20])
    return {"ok": True, "usuario": usuario, "roles": roles}


@router.post("/baja")
def baja_dispositivo(body: BajaIn):
    """Al cerrar sesión: este teléfono deja de recibir avisos de ese usuario."""
    return {"ok": repo_dispositivos.dar_de_baja(body.token)}


@router.post("/prueba")
def prueba(body: PruebaIn):
    """Manda una notificación de prueba a un usuario o a un rol (para comprobar que todo está conectado)."""
    if not push.configurado():
        raise HTTPException(503, "Firebase no está configurado en el servidor (falta FIREBASE_CREDENCIALES)")
    if body.usuario:
        return push.enviar_a_usuario(body.usuario, body.titulo, body.cuerpo, {"tipo": "prueba"})
    if body.roles:
        return push.enviar_a_roles(body.roles, body.titulo, body.cuerpo, {"tipo": "prueba"})
    raise HTTPException(400, "Indica un usuario o una lista de roles")


@router.get("/estado")
def estado():
    return push.estado()
