"""Teléfonos que recibirán notificaciones push (token de Firebase por dispositivo y a qué usuario pertenece)."""
import json
import time

from app.data.almacen import transaccion


def registrar(token: str, usuario: str, roles: list[str], plataforma: str = "android") -> None:
    """Un token pertenece a UN usuario: si alguien más inicia sesión en ese teléfono, el token cambia de dueño."""
    with transaccion() as c:
        c.execute(
            "INSERT INTO dispositivos(token,usuario,roles,plataforma,actualizado) VALUES(?,?,?,?,?) "
            "ON CONFLICT(token) DO UPDATE SET usuario=excluded.usuario, roles=excluded.roles, "
            "plataforma=excluded.plataforma, actualizado=excluded.actualizado",
            (token, usuario, json.dumps(roles), plataforma, time.time()))


def dar_de_baja(token: str) -> bool:
    with transaccion() as c:
        return c.execute("DELETE FROM dispositivos WHERE token=?", (token,)).rowcount > 0


def _fila(r) -> dict:
    return {"token": r["token"], "usuario": r["usuario"], "roles": json.loads(r["roles"] or "[]"),
            "plataforma": r["plataforma"], "actualizado": r["actualizado"]}


def de_usuario(usuario: str) -> list[dict]:
    with transaccion() as c:
        return [_fila(r) for r in c.execute("SELECT * FROM dispositivos WHERE usuario=?", (usuario,))]


def de_roles(roles: list[str]) -> list[dict]:
    """Los dispositivos de cualquier usuario que tenga alguno de esos roles."""
    pedidos = set(roles)
    with transaccion() as c:
        todos = [_fila(r) for r in c.execute("SELECT * FROM dispositivos")]
    return [d for d in todos if pedidos & set(d["roles"])]


def contar() -> int:
    with transaccion() as c:
        return c.execute("SELECT COUNT(*) n FROM dispositivos").fetchone()["n"]
