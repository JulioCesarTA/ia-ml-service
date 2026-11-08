"""Telegram del comedor.

- Los avisos para aprobar llegan SOLO a los chats de usuarios con rol administrador (vinculados por correo).
- Los mensajes se guardan primero en una cola local (SQLite): si no hay internet salen solos al volver la red.
- Se reciben mensajes y botones con long-polling (getUpdates): no hace falta IP pública ni webhook.
  Con TELEGRAM_RECEPCION=n8n la recepción y el envío los hace n8n: llama a `procesar_evento` y ejecuta las acciones que devuelve.
- La conversación con cada persona (menú, quién soy, reservar y pagar) vive en `asistente`.
"""
import contextvars
import os
import threading
import time

from app.data import repo_config, repo_telegram, telegram_api
from app.services import identidad, propuestas

_despertar = threading.Event()
_estado = {"ultimo_error": None, "ultimo_envio": None}
RECEPCION_N8N = os.getenv("TELEGRAM_RECEPCION", "interna").lower() == "n8n"
_SALIENTES = {"sendMessage", "answerCallbackQuery", "editMessageReplyMarkup", "deleteMessage"}
_captura: contextvars.ContextVar[list | None] = contextvars.ContextVar("captura_telegram", default=None)


def configurado() -> bool:
    return bool(telegram_api.token())


def _api(metodo: str, _espera: float = 15, **payload) -> dict:
    acciones = _captura.get()
    if acciones is not None and metodo in _SALIENTES:     # n8n ejecuta estas llamadas
        acciones.append({"metodo": metodo, "datos": payload})
        return {}
    return telegram_api.llamar(metodo, _espera, **payload)


# ----------------------------- envío directo (conversación) -----------------------------

def enviar(chat: str, texto: str, botones: list[list[dict]] | None = None) -> dict:
    datos = {"chat_id": chat, "text": texto[:4000]}
    if botones:
        datos["reply_markup"] = {"inline_keyboard": botones}
    return _api("sendMessage", **datos)


def enviar_foto(chat: str, png: bytes, pie: str = "") -> None:
    telegram_api.enviar_foto(chat, png, pie)


def enviar_documento_url(chat: str, url: str, pie: str = "") -> None:
    _api("sendDocument", _espera=40, chat_id=chat, document=url, caption=pie[:1000])


def borrar(chat: str, message_id: int) -> None:
    try:
        _api("deleteMessage", chat_id=chat, message_id=message_id)
    except Exception:
        pass


def boton(texto: str, data: str) -> dict:
    return {"text": texto, "callback_data": data}


# ----------------------------- cola de avisos al administrador -----------------------------

def encolar(texto: str, propuesta_id: str | None = None, chat: str | None = None) -> None:
    """Guarda el mensaje. Sin `chat`, va a todos los administradores vinculados (espera si aún no hay ninguno)."""
    repo_telegram.encolar(texto[:4000], propuesta_id, chat)
    _despertar.set()


def estado() -> dict:
    en_cola = repo_telegram.mensajes_en_cola()
    admins = identidad.chats_admin()
    return {
        "configurado": configurado(),
        "vinculado": bool(admins),
        "administradores": len(admins),
        "chatsVinculados": len(identidad.chats_listos()),
        "mensajesEnCola": en_cola,
        "ultimoEnvio": _estado["ultimo_envio"],
        "ultimoError": _estado["ultimo_error"],
    }


def botones_propuesta(pid: str) -> list[list[dict]]:
    return [[boton("✅ Aprobar", f"ap:{pid}"), boton("❌ Rechazar", f"re:{pid}")]]


def _vaciar_cola() -> None:
    if not configurado():
        return
    admins = identidad.chats_admin()
    for f in repo_telegram.cola():
        destino = f["chat_id"]
        if destino is None:
            if not admins:
                continue                              # espera a que un administrador vincule su chat
            repo_telegram.repartir(f, admins)
            _despertar.set()
            continue
        pid = f["propuesta_id"]
        p = propuestas.obtener(pid) if pid else None
        con_botones = bool(p and p["estado"] == "PENDIENTE")     # si ya se resolvió en el panel, sin botones
        try:
            enviar(destino, f["texto"], botones_propuesta(pid) if con_botones else None)
            _estado["ultimo_envio"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _estado["ultimo_error"] = None
            borrar_fila = True
        except telegram_api.ErrorDeRed as e:            # sin internet: se reintenta luego
            _estado["ultimo_error"] = f"sin conexión: {str(e)[:80]}"
            return
        except Exception as e:                          # Telegram rechazó el mensaje: reintentos limitados
            _estado["ultimo_error"] = str(e)[:150]
            borrar_fila = f["intentos"] >= 4
            if not borrar_fila:
                repo_telegram.sumar_intento(f["id"])
        if borrar_fila:
            repo_telegram.quitar_de_cola(f["id"])


def _bucle_envio() -> None:
    while True:
        try:
            _vaciar_cola()
        except Exception as e:
            _estado["ultimo_error"] = str(e)[:150]
        _despertar.wait(timeout=10)
        _despertar.clear()


# ----------------------------- recepción -----------------------------

def _boton_propuesta(cb: dict) -> None:
    cid = str(cb["message"]["chat"]["id"])
    if not identidad.es_admin(cid):
        _api("answerCallbackQuery", callback_query_id=cb["id"], text="Solo un administrador puede aprobar o rechazar")
        return
    accion, _, pid = cb["data"].partition(":")
    previa = propuestas.obtener(pid)
    if previa is None:
        _api("answerCallbackQuery", callback_query_id=cb["id"], text="La propuesta ya no existe")
        return
    if previa["estado"] != "PENDIENTE":
        _api("answerCallbackQuery", callback_query_id=cb["id"], text=f"Ya estaba {previa['estado'].lower()}")
        res = previa
    else:
        _api("answerCallbackQuery", callback_query_id=cb["id"], text="Procesando…")
        res = propuestas.resolver(pid, accion == "ap", "Telegram")
    try:
        _api("editMessageReplyMarkup", chat_id=cid, message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
    except Exception:
        pass
    icono = {"EJECUTADA": "✅", "RECHAZADA": "❌", "ERROR": "⚠️"}.get(res["estado"], "ℹ️")
    encolar(f"{icono} {res['titulo']}\n{res['resultado'] or res['estado']}")


def _procesar(u: dict) -> None:
    from app.services import asistente          # import tardío: asistente usa este módulo
    if "callback_query" in u:
        cb = u["callback_query"]
        if cb.get("data", "")[:3] in ("ap:", "re:"):
            _boton_propuesta(cb)
        else:
            asistente.boton(cb)
    elif "message" in u:
        asistente.mensaje(u["message"])


def procesar_evento(u: dict) -> list[dict]:
    """Procesa un update de Telegram y devuelve las llamadas a la API de Telegram que debe hacer quien lo envió (n8n)."""
    acciones: list[dict] = []
    marca = _captura.set(acciones)
    try:
        _procesar(u)
    finally:
        _captura.reset(marca)
    return acciones


COMANDOS = [("start", "Mostrar el menú principal"), ("menu", "Ver el menú de comidas"), ("quiensoy", "Ver con qué cuenta estoy"),
            ("reservar", "Reservar una ración"), ("cambiar", "Cerrar sesión y entrar con otra cuenta")]


def _registrar_comandos() -> None:
    _api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMANDOS])


def _bucle_recepcion() -> None:
    comandos_listos = False
    while True:
        if not configurado():
            time.sleep(30)
            continue
        try:
            if not comandos_listos:
                _registrar_comandos()
                comandos_listos = True
            if RECEPCION_N8N:
                time.sleep(60)
                continue
            offset = int(repo_config.leer("offset") or 0)
            for u in _api("getUpdates", _espera=40, timeout=25, offset=offset, allowed_updates=["message", "callback_query"]):
                repo_config.escribir("offset", str(u["update_id"] + 1))
                try:
                    _procesar(u)
                except telegram_api.ErrorDeRed:
                    raise
                except Exception as e:
                    _estado["ultimo_error"] = str(e)[:150]
        except telegram_api.ErrorDeRed as e:
            _estado["ultimo_error"] = f"sin conexión: {str(e)[:80]}"
            time.sleep(10)
        except Exception as e:
            _estado["ultimo_error"] = str(e)[:150]
            time.sleep(10)


def iniciar() -> None:
    from app.services import asistente
    threading.Thread(target=_bucle_envio, daemon=True, name="telegram-envio").start()
    threading.Thread(target=_bucle_recepcion, daemon=True, name="telegram-recepcion").start()
    threading.Thread(target=asistente.bucle_pagos, daemon=True, name="telegram-pagos").start()
