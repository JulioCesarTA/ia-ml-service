"""Carga de los datos reales del comedor para los reportes (por HTTP a cada servicio, solo lectura).

Cada conjunto se devuelve como una tabla (DataFrame) con las columnas del catálogo. Las fechas están en hora de
Bolivia y los resultados se guardan unos segundos para que consultas seguidas sean instantáneas.
"""
import threading
import time
from datetime import date

import pandas as pd

from app.data import comedor_http, repo_vision

TZ = "America/La_Paz"
TTL = 10.0
TTL_GRANDES = 60.0          # reservas y pagos pueden ser miles de filas: se leen una vez por minuto
_lock = threading.Lock()
_cache: dict[str, tuple[float, pd.DataFrame]] = {}


class FuenteNoDisponible(Exception):
    pass


def _json(url: str):
    try:
        return comedor_http.leer_json(url)
    except Exception as e:
        raise FuenteNoDisponible(f"No pude leer los datos ({url.split('/')[2]}): {str(e)[:80]}")


def _fecha_dia(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _fecha_utc(s: pd.Series, normalizar: bool = True) -> pd.Series:
    d = pd.to_datetime(s, utc=True, errors="coerce").dt.tz_convert(TZ).dt.tz_localize(None)
    return d.dt.normalize() if normalizar else d


def _plato(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"^plato-", "", regex=True)


# ----------------------------- conjuntos -----------------------------

def _reservas() -> pd.DataFrame:
    filas = _json(comedor_http.url("comensales") + "/analitica/reservas")
    df = pd.DataFrame(filas, columns=["id", "fecha", "turno", "plato", "estado", "creada", "matricula", "estudiante", "menuId"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["creada"] = _fecha_utc(df["creada"], normalizar=False)
    df["plato"] = _plato(df["plato"])
    df["estado"] = df["estado"].str.capitalize()
    df["turno"] = df["turno"].str.capitalize()
    return df[["fecha", "turno", "plato", "estado", "estudiante", "matricula", "creada"]]


def _pagos() -> pd.DataFrame:
    filas = _json(comedor_http.url("pagos") + "/pagos")
    df = pd.DataFrame(filas, columns=["id", "reservaId", "estudiante", "monto", "metodo", "estado", "ticketId", "fecha"])
    df["fecha"] = _fecha_utc(df["fecha"])
    df["monto"] = pd.to_numeric(df["monto"], errors="coerce").fillna(0.0)
    df["metodo"] = df["metodo"].replace({"qr_bancario": "QR / tarjeta", "beca": "Beca", "efectivo": "Efectivo"})
    df["estado"] = df["estado"].str.capitalize()
    df = df.rename(columns={"reservaId": "reserva", "ticketId": "ticket"})
    return df[["fecha", "estudiante", "monto", "metodo", "estado", "reserva", "ticket"]]


def _becas() -> pd.DataFrame:
    filas = _json(comedor_http.url("comensales") + "/analitica/becas")
    df = pd.DataFrame(filas, columns=["id", "matricula", "estudiante", "tipo", "cupoMensual", "usadas", "desde", "hasta"])
    df["desde"] = _fecha_utc(df["desde"])
    df["hasta"] = _fecha_utc(df["hasta"])
    df["tipo"] = df["tipo"].str.capitalize()
    df["disponibles"] = df["cupoMensual"] - df["usadas"]
    df["uso"] = (df["usadas"] / df["cupoMensual"].replace(0, pd.NA) * 100).astype(float).round(1).fillna(0.0)
    hoy = pd.Timestamp(date.today())
    df["vigente"] = ((df["desde"] <= hoy) & (df["hasta"] >= hoy)).map({True: "Sí", False: "No"})
    return df[["estudiante", "matricula", "tipo", "cupoMensual", "usadas", "disponibles", "uso", "desde", "hasta", "vigente"]]


def _estudiantes() -> pd.DataFrame:
    est = pd.DataFrame(_json(comedor_http.url("comensales") + "/estudiantes"),
                       columns=["id", "registroUniv", "nombre", "email", "telefono"]).rename(columns={"registroUniv": "matricula"})
    becas = cargar("becas")
    vigentes = becas[becas["vigente"] == "Sí"].sort_values("desde").drop_duplicates("matricula", keep="last")
    est = est.merge(vigentes[["matricula", "tipo"]].rename(columns={"tipo": "beca"}), on="matricula", how="left")
    est["beca"] = est["beca"].fillna("Sin beca")
    res = cargar("reservas")
    cuenta = res[res["estado"] != "Cancelada"].groupby("matricula").size().rename("reservas")
    est = est.merge(cuenta, left_on="matricula", right_index=True, how="left")
    est["reservas"] = est["reservas"].fillna(0).astype(int)
    pag = cargar("pagos")
    pagado = pag[pag["estado"] == "Cobrado"].groupby("estudiante")["monto"].sum().rename("pagado")
    est = est.merge(pagado, left_on="matricula", right_index=True, how="left")
    est["pagado"] = est["pagado"].fillna(0.0)
    est["telefono"] = est["telefono"].fillna("")
    return est[["matricula", "nombre", "email", "telefono", "beca", "reservas", "pagado"]]


def _menus() -> pd.DataFrame:
    from app.services.analitica import datos
    filas = datos.filas(ttl=TTL)
    if not filas and not datos.fuente_ok():
        raise FuenteNoDisponible("No pude leer los menús (servicio de menús sin respuesta)")
    df = pd.DataFrame(filas, columns=["fecha", "turno", "platoId", "cupo", "apartadas"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["plato"] = _plato(df["platoId"])
    df["turno"] = df["turno"].str.capitalize()
    df["disponibles"] = df["cupo"] - df["apartadas"]
    df["ocupacion"] = (df["apartadas"] / df["cupo"].replace(0, pd.NA) * 100).astype(float).round(1).fillna(0.0)
    return df[["fecha", "turno", "plato", "cupo", "apartadas", "disponibles", "ocupacion"]]


def _insumos() -> pd.DataFrame:
    filas = []
    hoy = pd.Timestamp(date.today())
    for i in _json(comedor_http.url("menu") + "/insumos"):
        lotes = i.get("lotes") or []
        stock = sum(((l.get("cantidad") or {}).get("valor") or 0) for l in lotes)
        vence = [pd.to_datetime((l.get("vencimiento") or {}).get("fecha"), errors="coerce") for l in lotes]
        vence = [v.tz_localize(None) if v is not pd.NaT and v.tzinfo else v for v in vence]
        vence = [v for v in vence if v is not pd.NaT]
        prox = min(vence).normalize() if vence else pd.NaT
        minimo = float(i.get("stockMinimo") or 0)
        filas.append({"insumo": str(i.get("nombre", "")).capitalize(), "unidad": i.get("unidad"), "stock": float(stock), "minimo": minimo,
                      "estado": "Bajo" if stock <= minimo else "En rango", "lotes": len(lotes), "vence": prox,
                      "diasParaVencer": int((prox - hoy).days) if prox is not pd.NaT else None})
    return pd.DataFrame(filas, columns=["insumo", "unidad", "stock", "minimo", "estado", "lotes", "vence", "diasParaVencer"])


def _desperdicio() -> pd.DataFrame:
    filas = repo_vision.todas_las_bandejas()
    df = pd.DataFrame(filas, columns=["fecha", "turno", "plato_id", "restante", "comido", "confianza"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["plato"] = _plato(df["plato_id"])
    df["turno"] = df["turno"].astype(str).str.capitalize()
    df["confianza"] = (df["confianza"] * 100).round(0)
    return df[["fecha", "turno", "plato", "restante", "comido", "confianza"]]


CARGADORES = {"reservas": _reservas, "pagos": _pagos, "estudiantes": _estudiantes, "becas": _becas,
              "menus": _menus, "insumos": _insumos, "desperdicio": _desperdicio}


def invalidar() -> None:
    with _lock:
        _cache.clear()


def cargar(dataset: str) -> pd.DataFrame:
    with _lock:
        hit = _cache.get(dataset)
        if hit and time.time() - hit[0] < (TTL_GRANDES if dataset in ("reservas", "pagos") else TTL):
            return hit[1].copy()
    df = CARGADORES[dataset]()
    with _lock:
        _cache[dataset] = (time.time(), df)
    return df.copy()
