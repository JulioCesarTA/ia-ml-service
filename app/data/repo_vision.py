"""Visión: fotos de referencia de la porción completa y bandejas analizadas (tablas `ref_porcion` y `bandejas`)."""
import os
import time

from app.data.almacen import directorio_datos, transaccion


def directorio_fotos() -> str:
    d = os.path.join(directorio_datos(), "fotos")
    os.makedirs(d, exist_ok=True)
    return d


def guardar_referencia(rid: str, plato_id: str, fecha: str, turno: str, f_ref: float, advertencia: str | None,
                       foto_key: str | None = None, origen: str = "servidor", cliente_id: str | None = None) -> None:
    with transaccion() as c:
        c.execute("INSERT INTO ref_porcion(id,plato_id,fecha,turno,creado,f_ref,advertencia,foto_key,origen,cliente_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (rid, plato_id, fecha, turno, time.time(), f_ref, advertencia, foto_key, origen, cliente_id))


def por_cliente(tabla: str, cliente_id: str) -> dict | None:
    """Registro ya guardado con ese id de cliente (para que reenviar no duplique)."""
    assert tabla in ("ref_porcion", "bandejas")
    with transaccion() as c:
        r = c.execute(f"SELECT * FROM {tabla} WHERE cliente_id=?", (cliente_id,)).fetchone()
        return dict(r) if r else None


def foto_key(carpeta: str, fid: str) -> str | None:
    tabla = "ref_porcion" if carpeta == "ref" else "bandejas"
    with transaccion() as c:
        r = c.execute(f"SELECT foto_key FROM {tabla} WHERE id=?", (fid,)).fetchone()
        return r["foto_key"] if r else None


def referencias(limite: int) -> list[dict]:
    with transaccion() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ref_porcion ORDER BY creado DESC LIMIT ?", (limite,))]


def referencia(ref_id: str) -> dict | None:
    with transaccion() as c:
        r = c.execute("SELECT * FROM ref_porcion WHERE id=?", (ref_id,)).fetchone()
        return dict(r) if r else None


def guardar_bandeja(bid: str, ref_id: str, plato_id: str, fecha: str, turno: str,
                    restante: float, comido: float, confianza: float,
                    foto_key: str | None = None, origen: str = "servidor", cliente_id: str | None = None) -> None:
    with transaccion() as c:
        c.execute("INSERT INTO bandejas(id,ref_id,plato_id,fecha,turno,creado,restante,comido,confianza,foto_key,origen,cliente_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (bid, ref_id, plato_id, fecha, turno, time.time(), restante, comido, confianza, foto_key, origen, cliente_id))


def resumen_bandejas() -> dict:
    with transaccion() as c:
        total = c.execute("SELECT COUNT(*) n, AVG(restante) r FROM bandejas").fetchone()
        por_plato = [dict(x) for x in c.execute(
            "SELECT plato_id platoId, turno, COUNT(*) bandejas, ROUND(AVG(restante),1) restante, ROUND(AVG(comido),1) comido "
            "FROM bandejas GROUP BY plato_id, turno ORDER BY bandejas DESC")]
        por_dia = [dict(x) for x in c.execute(
            "SELECT fecha, COUNT(*) bandejas, ROUND(AVG(restante),1) restante FROM bandejas GROUP BY fecha ORDER BY fecha")]
        recientes = [dict(x) for x in c.execute(
            "SELECT id, ref_id refId, plato_id platoId, fecha, turno, creado, restante, comido, confianza FROM bandejas ORDER BY creado DESC LIMIT 12")]
    return {"bandejas": total["n"], "restanteMedio": total["r"], "porPlato": por_plato, "porDia": por_dia, "recientes": recientes}


def restante_medio_por_plato(minimo_bandejas: int) -> dict[str, float]:
    with transaccion() as c:
        return {r["plato_id"]: r["m"] for r in c.execute(
            "SELECT plato_id, AVG(restante) m FROM bandejas GROUP BY plato_id HAVING COUNT(*) >= ?", (minimo_bandejas,))}


def todas_las_bandejas() -> list[dict]:
    with transaccion() as c:
        return [dict(r) for r in c.execute("SELECT fecha, turno, plato_id, restante, comido, confianza FROM bandejas")]
