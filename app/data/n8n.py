"""Cliente de n8n: todas las notificaciones (Telegram y push) las envía n8n, no un microservicio (SPEC §9).

Con N8N_URL definida cada envío es un POST a un webhook de n8n. La clave compartida impide que un tercero use esos
webhooks, porque n8n está publicado. Si n8n no responde se lanza ErrorDeRed: el llamador decide reintentar más tarde.
"""
import os

import httpx

ErrorDeRed = httpx.TransportError


def activo() -> bool:
    return bool(os.getenv("N8N_URL", "").strip())


def llamar(webhook: str, cuerpo: dict, espera: float = 20) -> dict:
    r = httpx.post(f"{os.environ['N8N_URL'].rstrip('/')}/webhook/{webhook}", json=cuerpo,
                   headers={"X-Clave-Comedor": os.getenv("N8N_CLAVE", "")}, timeout=espera)
    if r.status_code >= 400:              # flujo apagado o caído: es un fallo de n8n, no del mensaje
        raise httpx.TransportError(f"n8n {webhook}: respondió {r.status_code}")
    return r.json()
