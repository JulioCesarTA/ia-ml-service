"""Lectura del JWT que llega en la cabecera Authorization (adaptador de entrada).

El gateway valida las firmas cuando la autenticación está activa: aquí solo se leen las afirmaciones del token.
Qué roles son válidos lo decide el dominio, no este adaptador.
"""
import base64
import json


def identidad_bearer(authorization: str | None) -> tuple[str | None, list[str]]:
    """(usuario, roles del realm) que dice el token; sin token o ilegible devuelve (None, [])."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None, []
    try:
        p = authorization.split(" ", 1)[1].split(".")[1]
        datos = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        roles = list((datos.get("realm_access") or {}).get("roles", []))
        for r in roles:
            hash(r)                     # un rol que no es texto invalida el token entero
        return datos.get("preferred_username"), roles
    except Exception:
        return None, []
