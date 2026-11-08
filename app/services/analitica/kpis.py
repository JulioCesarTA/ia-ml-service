"""Los 7 indicadores (KPI) clave del comedor, calculados en vivo con los datos reales de los demás servicios.

Cada KPI sale como {id, nombre, valor, unidad, detalle, estado, meta, grafico}; `estado` es ok | alerta | critico | sin_datos.
`grafico` trae los datos que necesita su gráfico específico (cada KPI se dibuja distinto).
"""
from datetime import date

import pandas as pd

from app.services.reportes import fuentes

DIAS_SERIE = 14
DIA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _kpi(id_: str, nombre: str, valor, unidad: str, detalle: str, estado: str, meta: str, grafico: dict | None = None) -> dict:
    return {"id": id_, "nombre": nombre, "valor": valor, "unidad": unidad, "detalle": detalle,
            "estado": estado, "meta": meta, "grafico": grafico or {}}


def _sin_datos(id_: str, nombre: str, meta: str, motivo: str) -> dict:
    return _kpi(id_, nombre, None, "", motivo, "sin_datos", meta)


def _estado(valor: float, bueno: float, regular: float, mayor_es_mejor: bool = True) -> str:
    if not mayor_es_mejor:
        valor, bueno, regular = -valor, -bueno, -regular
    return "ok" if valor >= bueno else "alerta" if valor >= regular else "critico"


def _dias(hoy: pd.Timestamp, n: int = DIAS_SERIE) -> pd.DatetimeIndex:
    return pd.date_range(hoy - pd.Timedelta(days=n - 1), hoy)


def _etiqueta(d: pd.Timestamp) -> str:
    return f"{DIA[d.weekday()]} {d.day}"


def _ocupacion(hoy: pd.Timestamp) -> dict:
    nombre, meta = "Ocupación de cupos", "≥ 70% de las porciones ofrecidas se reservan"
    m = fuentes.cargar("menus")
    m = m[m["fecha"] <= hoy]
    if m.empty or m["cupo"].sum() == 0:
        return _sin_datos("ocupacion", nombre, meta, "Todavía no hay menús publicados con cupo")
    ult = m[m["fecha"] > hoy - pd.Timedelta(days=DIAS_SERIE)]
    pct = ult["apartadas"].sum() / max(1, ult["cupo"].sum()) * 100
    por_dia = []
    for d in _dias(hoy):
        dia = ult[ult["fecha"] == d]
        por_dia.append({"dia": _etiqueta(d), "cupo": int(dia["cupo"].sum()), "reservadas": int(dia["apartadas"].sum())})
    por_turno = [{"turno": t, "cupo": int(g["cupo"].sum()), "reservadas": int(g["apartadas"].sum())}
                 for t, g in ult.groupby("turno")]
    return _kpi("ocupacion", nombre, round(pct, 1), "%",
                f"{int(ult['apartadas'].sum())} de {int(ult['cupo'].sum())} porciones reservadas en {DIAS_SERIE} días",
                _estado(pct, 70, 40), meta, {"porDia": por_dia, "porTurno": por_turno})


def _ingresos(hoy: pd.Timestamp) -> dict:
    nombre, meta = "Ingresos cobrados", "Crecer semana a semana"
    p = fuentes.cargar("pagos")
    p = p[p["estado"] == "Cobrado"]
    if p.empty:
        return _sin_datos("ingresos", nombre, meta, "Todavía no hay pagos cobrados")
    ult7 = p[p["fecha"] > hoy - pd.Timedelta(days=7)]["monto"].sum()
    prev7 = p[(p["fecha"] <= hoy - pd.Timedelta(days=7)) & (p["fecha"] > hoy - pd.Timedelta(days=14))]["monto"].sum()
    variacion = (ult7 - prev7) / prev7 * 100 if prev7 else None
    detalle = f"Total histórico {round(p['monto'].sum(), 2)} Bs · " + (
        f"{'+' if variacion >= 0 else ''}{round(variacion, 1)}% vs. la semana anterior" if variacion is not None else "sin semana anterior para comparar")
    diario = p.groupby(p["fecha"].dt.normalize())["monto"].sum().reindex(_dias(hoy), fill_value=0)
    acumulado = diario.cumsum()
    por_metodo = [{"metodo": m, "monto": round(float(v), 2)} for m, v in p.groupby("metodo")["monto"].sum().items() if v > 0]
    return _kpi("ingresos", nombre, round(float(ult7), 2), "Bs (últimos 7 días)", detalle,
                "ok" if variacion is None or variacion >= 0 else "alerta", meta,
                {"porDia": [{"dia": _etiqueta(d), "monto": round(float(v), 2), "acumulado": round(float(acumulado[d]), 2)} for d, v in diario.items()],
                 "porMetodo": por_metodo})


def _volumen(hoy: pd.Timestamp) -> dict:
    nombre, meta = "Reservas de la semana", "Mantener o crecer frente a la semana anterior"
    r = fuentes.cargar("reservas")
    r = r[r["estado"] != "Cancelada"]
    if r.empty:
        return _sin_datos("volumen", nombre, meta, "Todavía no hay reservas")
    por_dia = r.groupby(r["fecha"].dt.normalize()).size()
    actual = _dias(hoy, 7)
    comparativo = []
    for d in actual:
        antes = d - pd.Timedelta(days=7)
        comparativo.append({"dia": f"{DIA[d.weekday()]}", "actual": int(por_dia.get(d, 0)), "anterior": int(por_dia.get(antes, 0))})
    ult7 = sum(c["actual"] for c in comparativo)
    prev7 = sum(c["anterior"] for c in comparativo)
    variacion = (ult7 - prev7) / prev7 * 100 if prev7 else None
    detalle = f"{prev7} la semana anterior" + (f" · {'+' if variacion >= 0 else ''}{round(variacion, 1)}%" if variacion is not None else "")
    return _kpi("volumen", nombre, ult7, "reservas (7 días)", detalle,
                "ok" if variacion is None or variacion >= -10 else "alerta", meta, {"comparativo": comparativo})


def _cancelacion() -> dict:
    nombre, meta = "Tasa de cancelación", "≤ 10% de las reservas se cancelan"
    r = fuentes.cargar("reservas")
    if r.empty:
        return _sin_datos("cancelacion", nombre, meta, "Todavía no hay reservas")
    canceladas = int((r["estado"] == "Cancelada").sum())
    pct = canceladas / len(r) * 100
    estados = [{"estado": e, "cantidad": int(c)} for e, c in r["estado"].value_counts().items()]
    return _kpi("cancelacion", nombre, round(pct, 1), "%",
                f"{canceladas} canceladas de {len(r)} reservas",
                _estado(pct, 10, 25, mayor_es_mejor=False), meta, {"estados": estados})


def _becas() -> dict:
    nombre, meta = "Uso de becas", "Becarios aprovechando su cupo mensual (≥ 50%)"
    b = fuentes.cargar("becas")
    b = b[b["vigente"] == "Sí"]
    if b.empty or b["cupoMensual"].sum() == 0:
        return _sin_datos("becas", nombre, meta, "No hay becas vigentes")
    pct = b["usadas"].sum() / b["cupoMensual"].sum() * 100
    padron = len(fuentes.cargar("estudiantes"))
    becarios = [{"nombre": str(f["estudiante"])[:18], "usadas": int(f["usadas"]), "libres": int(max(0, f["cupoMensual"] - f["usadas"]))}
                for f in b.sort_values("usadas", ascending=False).head(8).to_dict("records")]
    return _kpi("becas", nombre, round(pct, 1), "%",
                f"{len(b)} becarios vigentes de {padron} estudiantes · {int(b['usadas'].sum())} de {int(b['cupoMensual'].sum())} raciones usadas",
                _estado(pct, 50, 20), meta, {"becarios": becarios})


def _desperdicio() -> dict:
    nombre, meta = "Desperdicio de comida", "≤ 15% de la porción queda en la bandeja"
    d = fuentes.cargar("desperdicio")
    if d.empty:
        return _sin_datos("desperdicio", nombre, meta, "Aún no se analizaron bandejas con foto")
    pct = float(d["restante"].mean())
    por_plato = d.groupby("plato").agg(restante=("restante", "mean"), comido=("comido", "mean"), bandejas=("restante", "size"))
    por_plato = por_plato.sort_values("restante", ascending=False)
    platos = [{"plato": p, "restante": round(float(f["restante"]), 1), "comido": round(float(f["comido"]), 1), "bandejas": int(f["bandejas"])}
              for p, f in por_plato.head(8).iterrows()]
    return _kpi("desperdicio", nombre, round(pct, 1), "%",
                f"{len(d)} bandejas analizadas · más sobras: {por_plato.index[0]} ({round(float(por_plato.iloc[0]['restante']), 1)}%)",
                _estado(pct, 15, 30, mayor_es_mejor=False) if len(d) >= 3 else "alerta", meta, {"platos": platos})


def _insumos() -> dict:
    nombre, meta = "Insumos en riesgo", "0 insumos con stock bajo o por vencer"
    i = fuentes.cargar("insumos")
    if i.empty:
        return _sin_datos("insumos", nombre, meta, "No hay insumos registrados")
    bajos = i["estado"] == "Bajo"
    por_vencer = i["diasParaVencer"].notna() & (i["diasParaVencer"] <= 7)
    n = int((bajos | por_vencer).sum())
    items = [{"insumo": f["insumo"], "dias": None if pd.isna(f["diasParaVencer"]) else int(f["diasParaVencer"]),
              "bajo": f["estado"] == "Bajo", "stock": round(float(f["stock"]), 1), "minimo": round(float(f["minimo"]), 1), "unidad": f["unidad"]}
             for f in i.sort_values("diasParaVencer", na_position="last").to_dict("records")]
    return _kpi("insumos", nombre, n, f"de {len(i)} insumos",
                f"{int(bajos.sum())} con stock bajo · {int(por_vencer.sum())} vencen en 7 días o menos",
                "ok" if n == 0 else "alerta" if n <= max(1, len(i) // 4) else "critico", meta, {"items": items})


def calcular() -> dict:
    hoy = pd.Timestamp(date.today())
    calculadores = [lambda: _ocupacion(hoy), lambda: _ingresos(hoy), lambda: _volumen(hoy), _cancelacion,
                    _becas, _desperdicio, _insumos]
    kpis = []
    for f in calculadores:
        try:
            kpis.append(f())
        except Exception as e:                      # un servicio caído no tumba a los demás indicadores
            kpis.append(_kpi("error", "No disponible", None, "", f"No pude calcularlo: {str(e)[:100]}", "sin_datos", ""))
    return {"generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), "kpis": kpis}
