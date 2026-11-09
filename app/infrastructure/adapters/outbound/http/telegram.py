"""Cliente de la API de Telegram (puerto ClienteTelegram). Con n8n activo, n8n hace el envío; sin n8n (desarrollo
local) se llama directo a la Bot API."""
import base64
import os

import httpx

from app.application.ports.errores import ErrorDeRed
from app.application.ports.externos import MotorFlujos


def token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _url(metodo: str) -> str:
    return f"{os.getenv('TELEGRAM_API_URL', 'https://api.telegram.org')}/bot{token()}/{metodo}"


class ClienteTelegramHttp:
    def __init__(self, n8n: MotorFlujos):
        self._n8n = n8n

    def configurado(self) -> bool:
        return bool(token())

    def llamar(self, metodo: str, espera: float = 15, **payload):
        if self._n8n.activo():
            j = self._n8n.llamar("notificar", {"canal": "telegram", "metodo": metodo, "datos": payload}, espera + 5)
        else:
            try:
                j = httpx.post(_url(metodo), json=payload, timeout=espera).json()
            except httpx.TransportError as e:          # sin internet: el llamador decide reintentar más tarde
                raise ErrorDeRed(str(e), tipo=type(e).__name__) from e
        if not j.get("ok"):
            raise RuntimeError(f"Telegram {metodo}: {j.get('description', 'sin detalle')}")
        return j.get("result") or {}

    def enviar_foto(self, chat: str, png: bytes, pie: str) -> None:
        if self._n8n.activo():
            j = self._n8n.llamar("notificar-foto", {"chat_id": chat, "caption": pie[:1000], "png": base64.b64encode(png).decode()}, 35)
        else:
            try:
                j = httpx.post(_url("sendPhoto"), data={"chat_id": chat, "caption": pie[:1000]},
                               files={"photo": ("qr.png", png, "image/png")}, timeout=30).json()
            except httpx.TransportError as e:
                raise ErrorDeRed(str(e), tipo=type(e).__name__) from e
        if not j.get("ok"):
            raise RuntimeError(f"Telegram sendPhoto: {j.get('description', 'sin detalle')}")
