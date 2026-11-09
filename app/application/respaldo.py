"""Respaldo de la base local (propuestas, referencias y bandejas, chats de Telegram) en el bucket, cada 6 horas.

Si el volumen del servidor se pierde, la última copia está en el bucket (carpeta respaldos/). Con versionado activo
en el bucket, cada subida conserva también las anteriores. El reloj es un adaptador de entrada.
"""
from datetime import date

from app.application.ports.externos import AlmacenObjetos
from app.application.ports.repositorios import RespaldoBaseLocal

CADA_SEGUNDOS = 6 * 3600


class ServicioRespaldo:
    def __init__(self, base: RespaldoBaseLocal, objetos: AlmacenObjetos):
        self._base = base
        self._objetos = objetos

    def configurado(self) -> bool:
        return self._objetos.configurado()

    def respaldar(self) -> str | None:
        """Copia consistente de la base -> bucket. Devuelve la clave subida o None."""
        if not self._objetos.configurado():
            return None
        datos = self._base.copia_consistente()
        ok = self._objetos.subir(f"respaldos/agentes-{date.today().isoformat()}.db", datos, "application/octet-stream")
        self._objetos.subir("respaldos/agentes-ultimo.db", datos, "application/octet-stream")
        return f"respaldos/agentes-{date.today().isoformat()}.db" if ok else None
