"""Propuestas de los agentes (tabla `propuestas`)."""
import json
import time
import uuid

from app.data.almacen import transaccion


def _fila(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["payload"] = json.loads(d["payload"] or "{}")
    return d


def obtener(pid: str) -> dict | None:
    with transaccion() as c:
        return _fila(c.execute("SELECT * FROM propuestas WHERE id=?", (pid,)).fetchone())


def listar(estado: str | None, limite: int) -> list[dict]:
    with transaccion() as c:
        if estado:
            rows = c.execute("SELECT * FROM propuestas WHERE estado=? ORDER BY creado DESC LIMIT ?", (estado, limite))
        else:
            rows = c.execute("SELECT * FROM propuestas ORDER BY creado DESC LIMIT ?", (limite,))
        return [_fila(r) for r in rows.fetchall()]


def crear_si_no_hay_vigente(tipo: str, clave: str, titulo: str, resumen: str, payload: dict,
                            forzar: bool, informativa: bool, ventana_s: float) -> tuple[dict, bool]:
    """Devuelve (propuesta, es_nueva). Si ya hay una pendiente (o una reciente, salvo `forzar`) con la misma clave, la reutiliza."""
    ahora = time.time()
    with transaccion() as c:
        previa = c.execute(
            "SELECT * FROM propuestas WHERE tipo=? AND clave=? AND (estado='PENDIENTE' OR (?=0 AND creado>?)) "
            "ORDER BY creado DESC LIMIT 1",
            (tipo, clave, 1 if forzar else 0, ahora - ventana_s)).fetchone()
        if previa:
            return _fila(previa), False
        pid = uuid.uuid4().hex[:8]
        estado = "INFORMATIVA" if informativa else "PENDIENTE"
        c.execute("INSERT INTO propuestas VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (pid, tipo, clave, titulo, resumen, json.dumps(payload), estado, ahora, None, None))
        return _fila(c.execute("SELECT * FROM propuestas WHERE id=?", (pid,)).fetchone()), True


def tomar_pendiente(pid: str, nuevo_estado: str, resultado: str | None = None) -> bool:
    """Pasa de PENDIENTE a `nuevo_estado` solo si sigue pendiente (así dos canales no la deciden a la vez).
    Con `resultado` la deja además cerrada."""
    with transaccion() as c:
        cur = c.execute("UPDATE propuestas SET estado=? WHERE id=? AND estado='PENDIENTE'", (nuevo_estado, pid))
        if cur.rowcount == 0:
            return False
        if resultado is not None:
            c.execute("UPDATE propuestas SET resuelto=?, resultado=? WHERE id=?", (time.time(), resultado, pid))
        return True


def cerrar(pid: str, estado: str, resultado: str) -> None:
    with transaccion() as c:
        c.execute("UPDATE propuestas SET estado=?, resuelto=?, resultado=? WHERE id=?", (estado, time.time(), resultado, pid))
