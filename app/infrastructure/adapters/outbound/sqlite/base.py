"""SQLite local del servicio (funciona sin internet): ubicación, esquema y bloqueo compartidos por los repositorios."""
import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from typing import Iterator


def directorio_datos() -> str:
    d = os.getenv("AGENTES_DATA_DIR", "/data")
    try:
        os.makedirs(d, exist_ok=True)
        if os.access(d, os.W_OK):
            return d
    except OSError:
        pass
    logging.getLogger(__name__).error("No se puede escribir en %s: los datos se guardan en un temporal y se perderán al reiniciar", d)
    return tempfile.gettempdir()


class BaseLocal:
    """El archivo `agentes.db`. El esquema (tablas, columnas, migraciones e índices) no debe cambiar: hay datos en producción."""

    def __init__(self, directorio: str):
        self.directorio = directorio
        self.ruta = os.path.join(directorio, "agentes.db")
        self._lock = threading.RLock()
        self._iniciar()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.ruta, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    @contextmanager
    def transaccion(self) -> Iterator[sqlite3.Connection]:
        """Una conexión con el bloqueo tomado; confirma al salir y deshace si hubo error."""
        with self._lock, self._conn() as c:
            yield c

    def _iniciar(self) -> None:
        with self.transaccion() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS propuestas(
              id TEXT PRIMARY KEY, tipo TEXT, clave TEXT, titulo TEXT, resumen TEXT, payload TEXT,
              estado TEXT, creado REAL, resuelto REAL, resultado TEXT);
            CREATE TABLE IF NOT EXISTS outbox(
              id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT, propuesta_id TEXT,
              con_botones INTEGER DEFAULT 0, creado REAL, intentos INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS chats(
              chat_id TEXT PRIMARY KEY, estado TEXT, email TEXT, username TEXT, nombre TEXT,
              roles TEXT DEFAULT '[]', intentos INTEGER DEFAULT 0, ctx TEXT DEFAULT '{}', actualizado REAL);
            CREATE TABLE IF NOT EXISTS pagos_tg(
              reserva_id TEXT PRIMARY KEY, chat_id TEXT, referencia TEXT, plato TEXT, fecha TEXT, turno TEXT,
              estado TEXT, intentos INTEGER DEFAULT 0, creado REAL);
            CREATE TABLE IF NOT EXISTS ref_porcion(
              id TEXT PRIMARY KEY, plato_id TEXT, fecha TEXT, turno TEXT, creado REAL, f_ref REAL, advertencia TEXT);
            CREATE TABLE IF NOT EXISTS dispositivos(
              token TEXT PRIMARY KEY, usuario TEXT NOT NULL, roles TEXT DEFAULT '[]',
              plataforma TEXT DEFAULT 'android', actualizado REAL);
            CREATE TABLE IF NOT EXISTS bandejas(
              id TEXT PRIMARY KEY, ref_id TEXT, plato_id TEXT, fecha TEXT, turno TEXT, creado REAL,
              restante REAL, comido REAL, confianza REAL);
            """)
            cols = [r["name"] for r in c.execute("PRAGMA table_info(outbox)")]
            if "chat_id" not in cols:                      # base creada antes de que hubiera varios destinatarios
                c.execute("ALTER TABLE outbox ADD COLUMN chat_id TEXT")
            for tabla in ("ref_porcion", "bandejas"):      # fotos en S3 y registros hechos desde el celular
                existentes = [r["name"] for r in c.execute(f"PRAGMA table_info({tabla})")]
                # sectores: JSON con el % que quedó de cada sector (arroz, ensalada, ...); columna nueva, las filas viejas quedan en NULL
                for col, tipo in (("foto_key", "TEXT"), ("origen", "TEXT DEFAULT 'servidor'"), ("cliente_id", "TEXT"), ("sectores", "TEXT")):
                    if col not in existentes:
                        c.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
                # un mismo registro enviado dos veces (reintento sin conexión) no se duplica ni se pisa
                c.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{tabla}_cliente ON {tabla}(cliente_id) WHERE cliente_id IS NOT NULL")
