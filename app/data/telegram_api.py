"""Cliente de la API de Telegram (Bot API). Con n8n activo, n8n hace el envío; sin n8n (desarrollo local) se llama directo."""
import base64
import os

import httpx

from app.data import n8n

ErrorDeRed = httpx.TransportError          # sin internet: el llamador decide reintentar más tarde


def token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _url(metodo: str) -> str:
    return f"{os.getenv('TELEGRAM_API_URL', 'https://api.telegram.org')}/bot{token()}/{metodo}"


def llamar(metodo: str, espera: float = 15, **payload) -> dict:
    if n8n.activo():
        j = n8n.llamar("notificar", {"canal": "telegram", "metodo": metodo, "datos": payload}, espera + 5)
    else:
        j = httpx.post(_url(metodo), json=payload, timeout=espera).json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {j.get('description', 'sin detalle')}")
    return j.get("result") or {}


def enviar_foto(chat: str, png: bytes, pie: str) -> None:
    if n8n.activo():
        j = n8n.llamar("notificar", {"canal": "telegram-foto", "chat_id": chat, "caption": pie[:1000],
                                     "png": base64.b64encode(png).decode()}, 35)
    else:
        j = httpx.post(_url("sendPhoto"), data={"chat_id": chat, "caption": pie[:1000]},
                       files={"photo": ("qr.png", png, "image/png")}, timeout=30).json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram sendPhoto: {j.get('description', 'sin detalle')}")
