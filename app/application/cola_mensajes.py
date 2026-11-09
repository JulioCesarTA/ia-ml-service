"""Cola local de avisos a Telegram: los mensajes se guardan primero (sin internet salen solos al volver la red).

La usan las propuestas, los agentes y el bot; el envío lo hace `ServicioTelegram`, que espera en `despertar`.
"""
import threading

from app.application.ports.repositorios import RepositorioMensajes


class ColaMensajes:
    def __init__(self, repo: RepositorioMensajes):
        self.repo = repo
        self.despertar = threading.Event()

    def encolar(self, texto: str, propuesta_id: str | None = None, chat: str | None = None) -> None:
        """Guarda el mensaje. Sin `chat`, va a todos los administradores vinculados (espera si aún no hay ninguno)."""
        self.repo.encolar(texto[:4000], propuesta_id, chat)
        self.despertar.set()
