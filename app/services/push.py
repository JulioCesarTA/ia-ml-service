"""Notificaciones push: el teléfono registra su token (`/agentes/push/dispositivo`) y aquí se elige a quién avisar.

El envío a Firebase Cloud Messaging lo hace n8n (flujo «notificar», SPEC §9); la credencial de Firebase vive allá.
Un push es "lo mejor posible": si n8n o Firebase no responden, el sistema sigue funcionando y el aviso sigue llegando
por Telegram. Los tokens que Firebase marca como inválidos se borran solos.
"""
import time

from app.data import n8n, repo_dispositivos

# Un push necesita internet para viajar, pero si el teléfono está SIN conexión Firebase lo guarda y lo entrega apenas
# vuelva la red. Se guarda 2 días (un aviso de stock de la semana pasada ya no sirve) y los avisos del mismo tipo se
# reemplazan entre sí: el teléfono recibe el último, no una pila de alertas repetidas.
VIGENCIA = "172800s"
CANAL = "avisos_comedor"
_estado = {"ultimo_envio": None, "ultimo_error": None, "enviados": 0}


def configurado() -> bool:
    return n8n.activo()


def _enviar_fcm(token: str, titulo: str, cuerpo: str, datos: dict[str, str]) -> tuple[bool, bool]:
    """(se entregó a Firebase, el token ya no sirve). No lanza."""
    if not configurado():
        return False, False
    try:
        r = n8n.llamar("notificar", {"canal": "push", "token": token, "titulo": titulo, "cuerpo": cuerpo, "datos": datos,
                                     "vigencia": VIGENCIA, "canalAndroid": CANAL})
    except Exception as e:                                   # n8n apagado o sin red
        _estado["ultimo_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return False, False
    if r.get("ok"):
        return True, False
    _estado["ultimo_error"] = str(r.get("description"))[:160]
    return False, bool(r.get("tokenInvalido"))


def _despachar(destinos: list[dict], titulo: str, cuerpo: str, datos: dict | None) -> dict:
    datos = {k: str(v) for k, v in (datos or {}).items()}
    vistos, enviados, fallidos, borrados = set(), 0, 0, 0
    for d in destinos:
        if d["token"] in vistos:
            continue
        vistos.add(d["token"])
        ok, muerto = _enviar_fcm(d["token"], titulo[:100], cuerpo[:400], datos)
        if ok:
            enviados += 1
        else:
            fallidos += 1
        if muerto and repo_dispositivos.dar_de_baja(d["token"]):
            borrados += 1
    if enviados:
        _estado["ultimo_envio"] = time.time()
        _estado["enviados"] += enviados
    return {"destinatarios": len(vistos), "enviados": enviados, "fallidos": fallidos, "tokensBorrados": borrados,
            "configurado": configurado()}


def enviar_a_roles(roles: list[str], titulo: str, cuerpo: str, datos: dict | None = None) -> dict:
    return _despachar(repo_dispositivos.de_roles(roles), titulo, cuerpo, datos)


def enviar_a_usuario(usuario: str, titulo: str, cuerpo: str, datos: dict | None = None) -> dict:
    return _despachar(repo_dispositivos.de_usuario(usuario), titulo, cuerpo, datos)


def estado() -> dict:
    return {"configurado": configurado(), "dispositivos": repo_dispositivos.contar(), **_estado}
