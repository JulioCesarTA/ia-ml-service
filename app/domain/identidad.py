"""Roles del comedor: cómo se llaman en el bot, cuál manda y quiénes confirman contraseña."""

ETIQUETA = {"administrador": "administrador", "cocina_almacen": "cocinero", "servicio_caja": "caja",
            "nutricionista": "nutricionista", "estudiante": "estudiante"}
PRIORIDAD = ["administrador", "cocinero", "caja", "nutricionista", "estudiante"]
PRIVILEGIADOS = {"administrador", "cocinero", "caja", "nutricionista"}   # estos confirman además su contraseña


def rol_principal(roles: list[str]) -> str:
    return next((r for r in PRIORIDAD if r in roles), roles[0] if roles else "usuario")


def usuario_desde_proveedor(u: dict, email: str) -> dict:
    """Usuario de Keycloak -> {username, email, roles[], rol, nombre} con los roles en el idioma del bot."""
    roles = [ETIQUETA[r] for r in u["roles"] if r in ETIQUETA]
    return {"username": u["username"], "email": email, "roles": roles, "rol": rol_principal(roles),
            "nombre": " ".join(x for x in (u["firstName"], u["lastName"]) if x) or u["username"]}


def usuario_desde_padron(e: dict, email: str) -> dict:
    """Estudiante del padrón que todavía no tiene cuenta de acceso."""
    return {"username": e["registroUniv"], "email": email, "roles": ["estudiante"], "rol": "estudiante", "nombre": e["nombre"]}
