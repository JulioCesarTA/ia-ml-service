"""Pares clave/valor de configuración (horarios de los agentes, clima guardado, posición de Telegram)."""
from app.data.almacen import transaccion


def leer(k: str) -> str | None:
    with transaccion() as c:
        r = c.execute("SELECT v FROM config WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None


def escribir(k: str, v: str) -> str:
    with transaccion() as c:
        c.execute("INSERT INTO config VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    return v
