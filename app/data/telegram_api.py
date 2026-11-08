"""Cliente de la API de Telegram (Bot API)."""
import os

import httpx

ErrorDeRed = httpx.TransportError          # sin internet: el llamador decide reintentar más tarde


def token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _url(metodo: str) -> str:
    return f"{os.getenv('TELEGRAM_API_URL', 'https://api.telegram.org')}/bot{token()}/{metodo}"


def llamar(metodo: str, espera: float = 15, **payload) -> dict:
    r = httpx.post(_url(metodo), json=payload, timeout=espera)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {j.get('description', r.status_code)}")
    return j["result"]


def enviar_foto(chat: str, png: bytes, pie: str) -> None:
    r = httpx.post(_url("sendPhoto"), data={"chat_id": chat, "caption": pie[:1000]},
                   files={"photo": ("qr.png", png, "image/png")}, timeout=30)
    if not r.json().get("ok"):
        raise RuntimeError(f"Telegram sendPhoto: {r.text[:150]}")
