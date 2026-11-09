"""Cliente de n8n (puerto MotorFlujos): todas las notificaciones (Telegram y push) las envía n8n (SPEC §9).

Con N8N_URL definida cada envío es un POST a un webhook de n8n. La clave compartida impide que un tercero use esos
webhooks, porque n8n está publicado. Si n8n no responde se lanza ErrorDeRed: el llamador decide reintentar más tarde.
"""
import os

import httpx

from app.application.ports.errores import ErrorDeRed


class ClienteN8n:
    def activo(self) -> bool:
        return bool(os.getenv("N8N_URL", "").strip())

    def llamar(self, webhook: str, cuerpo: dict, espera: float = 20) -> dict:
        try:
            r = httpx.post(f"{os.environ['N8N_URL'].rstrip('/')}/webhook/{webhook}", json=cuerpo,
                           headers={"X-Clave-Comedor": os.getenv("N8N_CLAVE", "")}, timeout=espera)
        except httpx.TransportError as e:
            raise ErrorDeRed(str(e), tipo=type(e).__name__) from e
        if r.status_code >= 400:              # flujo apagado o caído: es un fallo de n8n, no del mensaje
            raise ErrorDeRed(f"n8n {webhook}: respondió {r.status_code}", tipo="TransportError")
        return r.json()
