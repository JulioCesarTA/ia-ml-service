"""Reglas de las notificaciones push: roles válidos, vigencia, canal y validación del registro de un teléfono."""
from app.domain.errores import DatoInvalido

ROLES_VALIDOS = {"administrador", "nutricionista", "cocina_almacen", "servicio_caja", "estudiante"}

# Un push necesita internet para viajar, pero si el teléfono está SIN conexión Firebase lo guarda y lo entrega apenas
# vuelva la red. Se guarda 2 días (un aviso de stock de la semana pasada ya no sirve) y los avisos del mismo tipo se
# reemplazan entre sí: el teléfono recibe el último, no una pila de alertas repetidas.
VIGENCIA = "172800s"
CANAL = "avisos_comedor"


def roles_validos(roles: list[str]) -> list[str]:
    return [r for r in roles if r in ROLES_VALIDOS]


def validar_token_dispositivo(token: str) -> None:
    if not 20 <= len(token) <= 4096:
        raise DatoInvalido("El token del dispositivo no es válido")


def titular(usuario_token: str | None, roles_token: list[str], usuario_cuerpo: str | None,
            roles_cuerpo: list[str]) -> tuple[str, list[str]]:
    """Usuario y roles del dispositivo: los del token mandan (un teléfono no puede ascenderse a administrador);
    sin token se usa lo que dice el teléfono, pero solo con roles conocidos."""
    usuario = usuario_token or (usuario_cuerpo or "").strip()
    roles = roles_validos(roles_token) or roles_validos(roles_cuerpo)
    if not usuario:
        raise DatoInvalido("Falta el usuario")
    return usuario, roles


def datos_como_texto(datos: dict | None) -> dict[str, str]:
    return {k: str(v) for k, v in (datos or {}).items()}
