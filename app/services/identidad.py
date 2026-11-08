"""Quién es quien escribe al bot: correo institucional -> usuario y rol (Keycloak), con el padrón como respaldo."""
from app.data import comedor_http, keycloak_client, repo_telegram

ETIQUETA = {"administrador": "administrador", "cocina_almacen": "cocinero", "servicio_caja": "caja",
            "nutricionista": "nutricionista", "estudiante": "estudiante"}
PRIORIDAD = ["administrador", "cocinero", "caja", "nutricionista", "estudiante"]
PRIVILEGIADOS = {"administrador", "cocinero", "caja", "nutricionista"}   # estos confirman además su contraseña


def rol_principal(roles: list[str]) -> str:
    return next((r for r in PRIORIDAD if r in roles), roles[0] if roles else "usuario")


def buscar_por_email(email: str) -> dict | None:
    """{username, nombre, email, roles[], rol} o None. Lanza excepción si no hay conexión con Keycloak."""
    email = email.strip().lower()
    u = keycloak_client.usuario_por_email(email)
    if u:
        roles = [ETIQUETA[r] for r in u["roles"] if r in ETIQUETA]
        return {"username": u["username"], "email": email, "roles": roles, "rol": rol_principal(roles),
                "nombre": " ".join(x for x in (u["firstName"], u["lastName"]) if x) or u["username"]}
    # Respaldo: estudiante del padrón que todavía no tiene cuenta de acceso
    try:
        for e in comedor_http.estudiantes():
            if str(e.get("email", "")).strip().lower() == email:
                return {"username": e["registroUniv"], "email": email, "roles": ["estudiante"], "rol": "estudiante", "nombre": e["nombre"]}
    except Exception:
        pass
    return None


def verificar_password(username: str, password: str) -> bool:
    return keycloak_client.verificar_password(username, password)


# ----------------------------- chats vinculados -----------------------------

def chat(cid: str) -> dict | None:
    return repo_telegram.chat(cid)


def guardar_chat(cid: str, **campos) -> dict:
    return repo_telegram.guardar_chat(cid, **campos)


def borrar_chat(cid: str) -> None:
    repo_telegram.borrar_chat(cid)


def chats_listos() -> list[dict]:
    return repo_telegram.chats_listos()


def chats_admin() -> list[str]:
    """Los avisos para aprobar solo llegan (y solo se aceptan) desde chats de usuarios con rol administrador."""
    return [c["chat_id"] for c in chats_listos() if "administrador" in c["roles"]]


def es_admin(cid: str) -> bool:
    return cid in chats_admin()
