"""Repositorios SQLite: implementan los puertos de `app.application.ports.repositorios`."""
import json
import os
import sqlite3
import tempfile
import time
import uuid

from app.infrastructure.adapters.outbound.sqlite.base import BaseLocal


class _Repo:
    def __init__(self, base: BaseLocal):
        self._base = base

    def _tx(self):
        return self._base.transaccion()


# ----------------------------- propuestas -----------------------------

def _propuesta(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["payload"] = json.loads(d["payload"] or "{}")
    return d


class RepositorioPropuestasSqlite(_Repo):
    """Propuestas de los agentes (tabla `propuestas`)."""

    def obtener(self, pid: str) -> dict | None:
        with self._tx() as c:
            return _propuesta(c.execute("SELECT * FROM propuestas WHERE id=?", (pid,)).fetchone())

    def listar(self, estado: str | None, limite: int) -> list[dict]:
        with self._tx() as c:
            if estado:
                rows = c.execute("SELECT * FROM propuestas WHERE estado=? ORDER BY creado DESC LIMIT ?", (estado, limite))
            else:
                rows = c.execute("SELECT * FROM propuestas ORDER BY creado DESC LIMIT ?", (limite,))
            return [_propuesta(r) for r in rows.fetchall()]

    def crear_si_no_hay_vigente(self, tipo: str, clave: str, titulo: str, resumen: str, payload: dict,
                                forzar: bool, informativa: bool, ventana_s: float) -> tuple[dict, bool]:
        """Devuelve (propuesta, es_nueva). Si ya hay una pendiente (o una reciente, salvo `forzar`) con la misma clave, la reutiliza."""
        ahora = time.time()
        with self._tx() as c:
            previa = c.execute(
                "SELECT * FROM propuestas WHERE tipo=? AND clave=? AND (estado='PENDIENTE' OR (?=0 AND creado>?)) "
                "ORDER BY creado DESC LIMIT 1",
                (tipo, clave, 1 if forzar else 0, ahora - ventana_s)).fetchone()
            if previa:
                return _propuesta(previa), False
            pid = uuid.uuid4().hex[:8]
            estado = "INFORMATIVA" if informativa else "PENDIENTE"
            c.execute("INSERT INTO propuestas VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (pid, tipo, clave, titulo, resumen, json.dumps(payload), estado, ahora, None, None))
            return _propuesta(c.execute("SELECT * FROM propuestas WHERE id=?", (pid,)).fetchone()), True

    def tomar_pendiente(self, pid: str, nuevo_estado: str, resultado: str | None = None) -> bool:
        """Pasa de PENDIENTE a `nuevo_estado` solo si sigue pendiente (así dos canales no la deciden a la vez).
        Con `resultado` la deja además cerrada."""
        with self._tx() as c:
            cur = c.execute("UPDATE propuestas SET estado=? WHERE id=? AND estado='PENDIENTE'", (nuevo_estado, pid))
            if cur.rowcount == 0:
                return False
            if resultado is not None:
                c.execute("UPDATE propuestas SET resuelto=?, resultado=? WHERE id=?", (time.time(), resultado, pid))
            return True

    def cerrar(self, pid: str, estado: str, resultado: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE propuestas SET estado=?, resuelto=?, resultado=? WHERE id=?", (estado, time.time(), resultado, pid))


# ----------------------------- Telegram: cola, chats y pagos -----------------------------

class RepositorioMensajesSqlite(_Repo):
    """Cola de mensajes a Telegram (tabla `outbox`)."""

    def encolar(self, texto: str, propuesta_id: str | None, chat_id: str | None, con_botones: int | None = None,
                creado: float | None = None) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO outbox(texto, propuesta_id, con_botones, creado, chat_id) VALUES(?,?,?,?,?)",
                      (texto, propuesta_id, (1 if propuesta_id else 0) if con_botones is None else con_botones,
                       time.time() if creado is None else creado, chat_id))

    def mensajes_en_cola(self) -> int:
        with self._tx() as c:
            return c.execute("SELECT COUNT(*) n FROM outbox").fetchone()["n"]

    def cola(self) -> list[dict]:
        with self._tx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM outbox ORDER BY id")]

    def repartir(self, mensaje: dict, destinos: list[str]) -> None:
        """Cambia un mensaje sin destinatario por uno igual para cada chat."""
        with self._tx() as c:
            for chat in destinos:
                c.execute("INSERT INTO outbox(texto, propuesta_id, con_botones, creado, chat_id) VALUES(?,?,?,?,?)",
                          (mensaje["texto"], mensaje["propuesta_id"], mensaje["con_botones"], mensaje["creado"], chat))
            c.execute("DELETE FROM outbox WHERE id=?", (mensaje["id"],))

    def sumar_intento(self, mensaje_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE outbox SET intentos=intentos+1 WHERE id=?", (mensaje_id,))

    def quitar_de_cola(self, mensaje_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM outbox WHERE id=?", (mensaje_id,))


def _chat(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["roles"] = json.loads(d["roles"] or "[]")
    d["ctx"] = json.loads(d["ctx"] or "{}")
    return d


class RepositorioChatsSqlite(_Repo):
    """Chats vinculados (tabla `chats`)."""

    def chat(self, cid: str) -> dict | None:
        with self._tx() as c:
            return _chat(c.execute("SELECT * FROM chats WHERE chat_id=?", (cid,)).fetchone())

    def guardar_chat(self, cid: str, **campos) -> dict:
        with self._tx() as c:
            c.execute("INSERT OR IGNORE INTO chats(chat_id, estado, actualizado) VALUES(?,?,?)", (cid, "pide_email", time.time()))
            for k, v in campos.items():
                if k in ("roles", "ctx"):
                    v = json.dumps(v)
                c.execute(f"UPDATE chats SET {k}=? WHERE chat_id=?", (v, cid))
            c.execute("UPDATE chats SET actualizado=? WHERE chat_id=?", (time.time(), cid))
            return _chat(c.execute("SELECT * FROM chats WHERE chat_id=?", (cid,)).fetchone())

    def borrar_chat(self, cid: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM chats WHERE chat_id=?", (cid,))

    def chats_listos(self) -> list[dict]:
        with self._tx() as c:
            return [_chat(r) for r in c.execute("SELECT * FROM chats WHERE estado='listo'")]


class RepositorioPagosTelegramSqlite(_Repo):
    """Pagos esperados por el bot (tabla `pagos_tg`)."""

    def guardar_pago(self, reserva_id: str, chat_id: str, referencia: str | None, plato: str, fecha: str, turno: str) -> None:
        with self._tx() as c:
            c.execute("INSERT OR REPLACE INTO pagos_tg VALUES(?,?,?,?,?,?,?,?,?)",
                      (reserva_id, chat_id, referencia, plato, fecha, turno, "esperando_pago", 0, time.time()))

    def pago(self, reserva_id: str) -> dict | None:
        with self._tx() as c:
            r = c.execute("SELECT * FROM pagos_tg WHERE reserva_id=?", (reserva_id,)).fetchone()
            return dict(r) if r else None

    def marcar_pago(self, reserva_id: str, estado: str, intentos: int = 0) -> None:
        with self._tx() as c:
            c.execute("UPDATE pagos_tg SET estado=?, intentos=? WHERE reserva_id=?", (estado, intentos, reserva_id))

    def pagos_en_curso(self) -> list[dict]:
        with self._tx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM pagos_tg WHERE estado IN ('esperando_pago','esperando_factura')")]


# ----------------------------- visión -----------------------------

class RepositorioVisionSqlite(_Repo):
    """Fotos de referencia de la porción completa y bandejas analizadas (tablas `ref_porcion` y `bandejas`)."""

    def guardar_referencia(self, rid: str, plato_id: str, fecha: str, turno: str, f_ref: float, advertencia: str | None,
                           foto_key: str | None = None, origen: str = "servidor", cliente_id: str | None = None) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO ref_porcion(id,plato_id,fecha,turno,creado,f_ref,advertencia,foto_key,origen,cliente_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (rid, plato_id, fecha, turno, time.time(), f_ref, advertencia, foto_key, origen, cliente_id))

    def por_cliente(self, tabla: str, cliente_id: str) -> dict | None:
        """Registro ya guardado con ese id de cliente (para que reenviar no duplique)."""
        assert tabla in ("ref_porcion", "bandejas")
        with self._tx() as c:
            r = c.execute(f"SELECT * FROM {tabla} WHERE cliente_id=?", (cliente_id,)).fetchone()
            return dict(r) if r else None

    def foto_key(self, carpeta: str, fid: str) -> str | None:
        tabla = "ref_porcion" if carpeta == "ref" else "bandejas"
        with self._tx() as c:
            r = c.execute(f"SELECT foto_key FROM {tabla} WHERE id=?", (fid,)).fetchone()
            return r["foto_key"] if r else None

    def referencias(self, limite: int) -> list[dict]:
        with self._tx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM ref_porcion ORDER BY creado DESC LIMIT ?", (limite,))]

    def referencia(self, ref_id: str) -> dict | None:
        with self._tx() as c:
            r = c.execute("SELECT * FROM ref_porcion WHERE id=?", (ref_id,)).fetchone()
            return dict(r) if r else None

    def guardar_bandeja(self, bid: str, ref_id: str, plato_id: str, fecha: str, turno: str,
                        restante: float, comido: float, confianza: float,
                        foto_key: str | None = None, origen: str = "servidor", cliente_id: str | None = None) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO bandejas(id,ref_id,plato_id,fecha,turno,creado,restante,comido,confianza,foto_key,origen,cliente_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (bid, ref_id, plato_id, fecha, turno, time.time(), restante, comido, confianza, foto_key, origen, cliente_id))

    def resumen_bandejas(self) -> dict:
        with self._tx() as c:
            total = c.execute("SELECT COUNT(*) n, AVG(restante) r FROM bandejas").fetchone()
            por_plato = [dict(x) for x in c.execute(
                "SELECT plato_id platoId, turno, COUNT(*) bandejas, ROUND(AVG(restante),1) restante, ROUND(AVG(comido),1) comido "
                "FROM bandejas GROUP BY plato_id, turno ORDER BY bandejas DESC")]
            por_dia = [dict(x) for x in c.execute(
                "SELECT fecha, COUNT(*) bandejas, ROUND(AVG(restante),1) restante FROM bandejas GROUP BY fecha ORDER BY fecha")]
            recientes = [dict(x) for x in c.execute(
                "SELECT id, ref_id refId, plato_id platoId, fecha, turno, creado, restante, comido, confianza FROM bandejas ORDER BY creado DESC LIMIT 12")]
        return {"bandejas": total["n"], "restanteMedio": total["r"], "porPlato": por_plato, "porDia": por_dia, "recientes": recientes}

    def restante_medio_por_plato(self, minimo_bandejas: int) -> dict[str, float]:
        with self._tx() as c:
            return {r["plato_id"]: r["m"] for r in c.execute(
                "SELECT plato_id, AVG(restante) m FROM bandejas GROUP BY plato_id HAVING COUNT(*) >= ?", (minimo_bandejas,))}

    def todas_las_bandejas(self) -> list[dict]:
        with self._tx() as c:
            return [dict(r) for r in c.execute("SELECT fecha, turno, plato_id, restante, comido, confianza FROM bandejas")]


# ----------------------------- push -----------------------------

def _dispositivo(r) -> dict:
    return {"token": r["token"], "usuario": r["usuario"], "roles": json.loads(r["roles"] or "[]"),
            "plataforma": r["plataforma"], "actualizado": r["actualizado"]}


class RepositorioDispositivosSqlite(_Repo):
    """Teléfonos que recibirán notificaciones push (token de Firebase por dispositivo y a qué usuario pertenece)."""

    def registrar(self, token: str, usuario: str, roles: list[str], plataforma: str = "android") -> None:
        """Un token pertenece a UN usuario: si alguien más inicia sesión en ese teléfono, el token cambia de dueño."""
        with self._tx() as c:
            c.execute(
                "INSERT INTO dispositivos(token,usuario,roles,plataforma,actualizado) VALUES(?,?,?,?,?) "
                "ON CONFLICT(token) DO UPDATE SET usuario=excluded.usuario, roles=excluded.roles, "
                "plataforma=excluded.plataforma, actualizado=excluded.actualizado",
                (token, usuario, json.dumps(roles), plataforma, time.time()))

    def dar_de_baja(self, token: str) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM dispositivos WHERE token=?", (token,)).rowcount > 0

    def de_usuario(self, usuario: str) -> list[dict]:
        with self._tx() as c:
            return [_dispositivo(r) for r in c.execute("SELECT * FROM dispositivos WHERE usuario=?", (usuario,))]

    def de_roles(self, roles: list[str]) -> list[dict]:
        """Los dispositivos de cualquier usuario que tenga alguno de esos roles."""
        pedidos = set(roles)
        with self._tx() as c:
            todos = [_dispositivo(r) for r in c.execute("SELECT * FROM dispositivos")]
        return [d for d in todos if pedidos & set(d["roles"])]

    def contar(self) -> int:
        with self._tx() as c:
            return c.execute("SELECT COUNT(*) n FROM dispositivos").fetchone()["n"]


# ----------------------------- configuración -----------------------------

class RepositorioConfigSqlite(_Repo):
    """Pares clave/valor de configuración (horarios de los agentes, clima guardado, posición de Telegram)."""

    def leer(self, k: str) -> str | None:
        with self._tx() as c:
            r = c.execute("SELECT v FROM config WHERE k=?", (k,)).fetchone()
            return r["v"] if r else None

    def escribir(self, k: str, v: str) -> str:
        with self._tx() as c:
            c.execute("INSERT INTO config VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        return v


# ----------------------------- respaldo -----------------------------

class RespaldoSqlite(_Repo):
    """Copia consistente de la base con la API de respaldo de SQLite."""

    def copia_consistente(self) -> bytes:
        tmp = os.path.join(tempfile.gettempdir(), "agentes-respaldo.db")
        origen, destino = sqlite3.connect(self._base.ruta), sqlite3.connect(tmp)
        try:
            origen.backup(destino)
        finally:
            origen.close(); destino.close()
        with open(tmp, "rb") as f:
            return f.read()
