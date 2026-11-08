"""Telegram: cola de mensajes (outbox), chats vinculados y pagos que se esperan por el bot."""
import json
import time

from app.data.almacen import transaccion


# ----------------------------- cola de mensajes -----------------------------

def encolar(texto: str, propuesta_id: str | None, chat_id: str | None, con_botones: int | None = None,
            creado: float | None = None) -> None:
    with transaccion() as c:
        c.execute("INSERT INTO outbox(texto, propuesta_id, con_botones, creado, chat_id) VALUES(?,?,?,?,?)",
                  (texto, propuesta_id, (1 if propuesta_id else 0) if con_botones is None else con_botones,
                   time.time() if creado is None else creado, chat_id))


def mensajes_en_cola() -> int:
    with transaccion() as c:
        return c.execute("SELECT COUNT(*) n FROM outbox").fetchone()["n"]


def cola() -> list[dict]:
    with transaccion() as c:
        return [dict(r) for r in c.execute("SELECT * FROM outbox ORDER BY id")]


def repartir(mensaje: dict, destinos: list[str]) -> None:
    """Cambia un mensaje sin destinatario por uno igual para cada chat."""
    with transaccion() as c:
        for chat in destinos:
            c.execute("INSERT INTO outbox(texto, propuesta_id, con_botones, creado, chat_id) VALUES(?,?,?,?,?)",
                      (mensaje["texto"], mensaje["propuesta_id"], mensaje["con_botones"], mensaje["creado"], chat))
        c.execute("DELETE FROM outbox WHERE id=?", (mensaje["id"],))


def sumar_intento(mensaje_id: int) -> None:
    with transaccion() as c:
        c.execute("UPDATE outbox SET intentos=intentos+1 WHERE id=?", (mensaje_id,))


def quitar_de_cola(mensaje_id: int) -> None:
    with transaccion() as c:
        c.execute("DELETE FROM outbox WHERE id=?", (mensaje_id,))


# ----------------------------- chats vinculados -----------------------------

def _chat(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["roles"] = json.loads(d["roles"] or "[]")
    d["ctx"] = json.loads(d["ctx"] or "{}")
    return d


def chat(cid: str) -> dict | None:
    with transaccion() as c:
        return _chat(c.execute("SELECT * FROM chats WHERE chat_id=?", (cid,)).fetchone())


def guardar_chat(cid: str, **campos) -> dict:
    with transaccion() as c:
        c.execute("INSERT OR IGNORE INTO chats(chat_id, estado, actualizado) VALUES(?,?,?)", (cid, "pide_email", time.time()))
        for k, v in campos.items():
            if k in ("roles", "ctx"):
                v = json.dumps(v)
            c.execute(f"UPDATE chats SET {k}=? WHERE chat_id=?", (v, cid))
        c.execute("UPDATE chats SET actualizado=? WHERE chat_id=?", (time.time(), cid))
        return _chat(c.execute("SELECT * FROM chats WHERE chat_id=?", (cid,)).fetchone())


def borrar_chat(cid: str) -> None:
    with transaccion() as c:
        c.execute("DELETE FROM chats WHERE chat_id=?", (cid,))


def chats_listos() -> list[dict]:
    with transaccion() as c:
        return [_chat(r) for r in c.execute("SELECT * FROM chats WHERE estado='listo'")]


# ----------------------------- pagos esperados por el bot -----------------------------

def guardar_pago(reserva_id: str, chat_id: str, referencia: str | None, plato: str, fecha: str, turno: str) -> None:
    with transaccion() as c:
        c.execute("INSERT OR REPLACE INTO pagos_tg VALUES(?,?,?,?,?,?,?,?,?)",
                  (reserva_id, chat_id, referencia, plato, fecha, turno, "esperando_pago", 0, time.time()))


def pago(reserva_id: str) -> dict | None:
    with transaccion() as c:
        r = c.execute("SELECT * FROM pagos_tg WHERE reserva_id=?", (reserva_id,)).fetchone()
        return dict(r) if r else None


def marcar_pago(reserva_id: str, estado: str, intentos: int = 0) -> None:
    with transaccion() as c:
        c.execute("UPDATE pagos_tg SET estado=?, intentos=? WHERE reserva_id=?", (estado, intentos, reserva_id))


def pagos_en_curso() -> list[dict]:
    with transaccion() as c:
        return [dict(r) for r in c.execute("SELECT * FROM pagos_tg WHERE estado IN ('esperando_pago','esperando_factura')")]
