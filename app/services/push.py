"""Notificaciones push con Firebase Cloud Messaging (API HTTP v1).

El teléfono registra su token (`/agentes/push/dispositivo`); aquí se envía a los dispositivos de un usuario o de un
rol. La credencial es la cuenta de servicio de Firebase: llega por FIREBASE_CREDENCIALES (el JSON completo, desde un
secreto de Kubernetes) o por FIREBASE_CREDENCIALES_ARCHIVO (ruta, para desarrollo).

Un push es "lo mejor posible": si Firebase no responde o no hay credencial, el sistema sigue funcionando y el aviso
sigue llegando por Telegram. Los tokens que Firebase marca como inválidos se borran solos.
"""
import json
import os
import threading
import time

import httpx

from app.data import repo_dispositivos

ALCANCE = "https://www.googleapis.com/auth/firebase.messaging"
CANAL = "avisos_comedor"
_estado = {"ultimo_envio": None, "ultimo_error": None, "enviados": 0}
_cred = {"info": None, "token": None, "vence": 0.0}
_lock = threading.Lock()


def _info() -> dict | None:
    if _cred["info"] is None:
        crudo = os.getenv("FIREBASE_CREDENCIALES")
        ruta = os.getenv("FIREBASE_CREDENCIALES_ARCHIVO")
        try:
            if crudo:
                _cred["info"] = json.loads(crudo)
            elif ruta and os.path.exists(ruta):
                _cred["info"] = json.load(open(ruta, encoding="utf-8"))
        except (ValueError, OSError) as e:
            _estado["ultimo_error"] = f"credencial de Firebase ilegible: {e}"
    return _cred["info"]


def configurado() -> bool:
    return bool(_info())


def _token_acceso() -> str:
    """Token OAuth2 de la cuenta de servicio (dura ~1 hora; se renueva solo)."""
    with _lock:
        if _cred["token"] and time.time() < _cred["vence"] - 60:
            return _cred["token"]
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        c = service_account.Credentials.from_service_account_info(_info(), scopes=[ALCANCE])
        c.refresh(Request())
        _cred["token"] = c.token
        _cred["vence"] = c.expiry.timestamp() if c.expiry else time.time() + 3000
        return _cred["token"]


def _enviar_fcm(token: str, titulo: str, cuerpo: str, datos: dict[str, str]) -> tuple[bool, bool]:
    """(se entregó a Firebase, el token ya no sirve). No lanza."""
    info = _info()
    if not info:
        return False, False
    try:
        r = httpx.post(
            f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send",
            headers={"Authorization": f"Bearer {_token_acceso()}"}, timeout=15,
            json={"message": {
                "token": token,
                "notification": {"title": titulo, "body": cuerpo},
                "data": datos,
                "android": {"priority": "HIGH", "notification": {"channel_id": CANAL}},
            }})
    except Exception as e:                                   # sin red, credencial inválida, etc.
        _estado["ultimo_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return False, False
    if r.status_code == 200:
        return True, False
    muerto = r.status_code in (404, 410) or "UNREGISTERED" in r.text or "INVALID_ARGUMENT" in r.text
    _estado["ultimo_error"] = f"FCM {r.status_code}: {r.text[:160]}"
    return False, muerto


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
