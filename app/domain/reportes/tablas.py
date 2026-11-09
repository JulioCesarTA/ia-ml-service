"""Cómo se convierten los datos crudos de cada servicio en las tablas del catálogo de reportes (pandas, cálculo puro).

Las fechas quedan en hora de Bolivia y las columnas en el mismo orden que el catálogo.
"""
from datetime import date

import pandas as pd

TZ = "America/La_Paz"


def _fecha_dia(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _fecha_utc(s: pd.Series, normalizar: bool = True) -> pd.Series:
    d = pd.to_datetime(s, utc=True, errors="coerce").dt.tz_convert(TZ).dt.tz_localize(None)
    return d.dt.normalize() if normalizar else d


def _plato(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"^plato-", "", regex=True)


def reservas(filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["id", "fecha", "turno", "plato", "estado", "creada", "matricula", "estudiante", "menuId"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["creada"] = _fecha_utc(df["creada"], normalizar=False)
    df["plato"] = _plato(df["plato"])
    df["estado"] = df["estado"].str.capitalize()
    df["turno"] = df["turno"].str.capitalize()
    return df[["fecha", "turno", "plato", "estado", "estudiante", "matricula", "creada"]]


def pagos(filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["id", "reservaId", "estudiante", "monto", "metodo", "estado", "ticketId", "fecha"])
    df["fecha"] = _fecha_utc(df["fecha"])
    df["monto"] = pd.to_numeric(df["monto"], errors="coerce").fillna(0.0)
    df["metodo"] = df["metodo"].replace({"qr_bancario": "QR / tarjeta", "beca": "Beca", "efectivo": "Efectivo"})
    df["estado"] = df["estado"].str.capitalize()
    df = df.rename(columns={"reservaId": "reserva", "ticketId": "ticket"})
    return df[["fecha", "estudiante", "monto", "metodo", "estado", "reserva", "ticket"]]


def becas(filas: list[dict], hoy: date | None = None) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["id", "matricula", "estudiante", "tipo", "cupoMensual", "usadas", "desde", "hasta"])
    df["desde"] = _fecha_utc(df["desde"])
    df["hasta"] = _fecha_utc(df["hasta"])
    df["tipo"] = df["tipo"].str.capitalize()
    df["disponibles"] = df["cupoMensual"] - df["usadas"]
    df["uso"] = (df["usadas"] / df["cupoMensual"].replace(0, pd.NA) * 100).astype(float).round(1).fillna(0.0)
    hoy = pd.Timestamp(hoy or date.today())
    df["vigente"] = ((df["desde"] <= hoy) & (df["hasta"] >= hoy)).map({True: "Sí", False: "No"})
    return df[["estudiante", "matricula", "tipo", "cupoMensual", "usadas", "disponibles", "uso", "desde", "hasta", "vigente"]]


def asistencia(filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["id", "fecha", "hora", "usuario", "rol", "tipo", "distancia", "ubicacion", "revisar"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["distancia"] = pd.to_numeric(df["distancia"], errors="coerce").fillna(0).astype(int)
    return df[["fecha", "hora", "usuario", "rol", "tipo", "distancia", "ubicacion", "revisar"]]


def estudiantes(filas: list[dict], becas_df: pd.DataFrame, reservas_df: pd.DataFrame, pagos_df: pd.DataFrame) -> pd.DataFrame:
    est = pd.DataFrame(filas, columns=["id", "registroUniv", "nombre", "email", "telefono"]).rename(columns={"registroUniv": "matricula"})
    vigentes = becas_df[becas_df["vigente"] == "Sí"].sort_values("desde").drop_duplicates("matricula", keep="last")
    est = est.merge(vigentes[["matricula", "tipo"]].rename(columns={"tipo": "beca"}), on="matricula", how="left")
    est["beca"] = est["beca"].fillna("Sin beca")
    cuenta = reservas_df[reservas_df["estado"] != "Cancelada"].groupby("matricula").size().rename("reservas")
    est = est.merge(cuenta, left_on="matricula", right_index=True, how="left")
    est["reservas"] = est["reservas"].fillna(0).astype(int)
    pagado = pagos_df[pagos_df["estado"] == "Cobrado"].groupby("estudiante")["monto"].sum().rename("pagado")
    est = est.merge(pagado, left_on="matricula", right_index=True, how="left")
    est["pagado"] = est["pagado"].fillna(0.0)
    est["telefono"] = est["telefono"].fillna("")
    return est[["matricula", "nombre", "email", "telefono", "beca", "reservas", "pagado"]]


def menus(filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["fecha", "turno", "platoId", "cupo", "apartadas"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["plato"] = _plato(df["platoId"])
    df["turno"] = df["turno"].str.capitalize()
    df["disponibles"] = df["cupo"] - df["apartadas"]
    df["ocupacion"] = (df["apartadas"] / df["cupo"].replace(0, pd.NA) * 100).astype(float).round(1).fillna(0.0)
    return df[["fecha", "turno", "plato", "cupo", "apartadas", "disponibles", "ocupacion"]]


def insumos(datos: list[dict], hoy: date | None = None) -> pd.DataFrame:
    filas = []
    hoy = pd.Timestamp(hoy or date.today())
    for i in datos:
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


def desperdicio(filas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["fecha", "turno", "plato_id", "restante", "comido", "confianza"])
    df["fecha"] = _fecha_dia(df["fecha"])
    df["plato"] = _plato(df["plato_id"])
    df["turno"] = df["turno"].astype(str).str.capitalize()
    df["confianza"] = (df["confianza"] * 100).round(0)
    return df[["fecha", "turno", "plato", "restante", "comido", "confianza"]]
