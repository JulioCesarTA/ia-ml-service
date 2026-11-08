"""Respaldo de la base local (propuestas, referencias y bandejas, chats de Telegram) en S3, cada 6 horas.

Si el volumen del servidor se pierde, la última copia está en el bucket (carpeta respaldos/). Con versionado activo
en el bucket, cada subida conserva también las anteriores.
"""
import os
import sqlite3
import tempfile
import threading
import time
from datetime import date

from app.data import almacen, s3_fotos

CADA_SEGUNDOS = 6 * 3600


def respaldar() -> str | None:
    """Copia consistente de la base (API de respaldo de SQLite) -> S3. Devuelve la clave subida o None."""
    if not s3_fotos.configurado():
        return None
    tmp = os.path.join(tempfile.gettempdir(), "agentes-respaldo.db")
    origen, destino = sqlite3.connect(almacen._DB), sqlite3.connect(tmp)
    try:
        origen.backup(destino)
    finally:
        origen.close(); destino.close()
    with open(tmp, "rb") as f:
        datos = f.read()
    ok = s3_fotos.subir(f"respaldos/agentes-{date.today().isoformat()}.db", datos, "application/octet-stream")
    s3_fotos.subir("respaldos/agentes-ultimo.db", datos, "application/octet-stream")
    return f"respaldos/agentes-{date.today().isoformat()}.db" if ok else None


def _bucle() -> None:
    time.sleep(90)                                   # deja arrancar el servicio antes del primer respaldo
    while True:
        try:
            respaldar()
        except Exception:
            pass                                     # el siguiente intento es en 6 horas; el servicio no se detiene por esto
        time.sleep(CADA_SEGUNDOS)


def iniciar() -> None:
    if s3_fotos.configurado():
        threading.Thread(target=_bucle, daemon=True, name="respaldo-s3").start()
