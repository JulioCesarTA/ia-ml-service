"""Reglas del agente monitor del comedor: 'Monitoreame el comedor y avisame lo importante.'

  - Detecta caídas de asistencia (comparando semana vs. promedio)
  - Platos con mucho desperdicio (>25%)
  - Costo por ración fuera de presupuesto (>7 Bs objetivo)
  - Devuelve un reporte diario clasificado por severidad (ALTA/MEDIA/BAJA)
    con una recomendación concreta por hallazgo.
"""
from datetime import date, timedelta

PRESUPUESTO_BS_RACION = 7.0           # SPEC: costo objetivo por ración
UMBRAL_DESPERDICIO_ALERTA = 0.25      # 25%
UMBRAL_CAIDA_ASISTENCIA = 0.20        # 20% debajo del promedio
TURNOS = ("DESAYUNO", "ALMUERZO", "CENA")

# (consulta predefinida, días hacia atrás) que necesita cada indicador
CONSULTAS = {"desperdicio": ("desperdicio_por_plato", 7), "asistencia": ("asistencia_diaria", 14),
             "costo": ("costo_por_racion", 7)}


def rango(hoy: date, dias: int) -> dict:
    return {"desde": (hoy - timedelta(days=dias)).isoformat(), "hasta": hoy.isoformat()}


def evaluar(objetivo: str, hoy: date, desp: list[dict], asist: list[dict], cos: list[dict], cocinar_hoy: dict) -> dict:
    hallazgos: list[dict] = []
    kpis: dict = {}

    # ------------- KPI 1: desperdicio -------------
    desp_alto = [d for d in desp if (d.get("pct") or 0) > UMBRAL_DESPERDICIO_ALERTA * 100]
    kpis["desperdicioPromedioPct"] = round(
        sum((d.get("pct") or 0) for d in desp) / max(1, len(desp)), 1
    )
    kpis["platosConDesperdicioAlto"] = len(desp_alto)
    for d in desp_alto:
        hallazgos.append({
            "tipo": "desperdicio",
            "severidad": "ALTA" if d["pct"] > 40 else "MEDIA",
            "mensaje": f"Plato '{d['plato_id']}' con {d['pct']}% de desperdicio",
            "recomendacion": "Reducir porción servida 15% o rotar del menú 2 semanas",
        })

    # ------------- KPI 2: asistencia -------------
    if asist:
        series = [a.get("total") or 0 for a in asist]
        promedio = sum(series) / len(series)
        ultimo = series[-1] if series else 0
        kpis["asistenciaPromedio14d"] = int(promedio)
        kpis["asistenciaUltimoDia"] = int(ultimo)
        if promedio > 0 and (promedio - ultimo) / promedio > UMBRAL_CAIDA_ASISTENCIA:
            hallazgos.append({
                "tipo": "asistencia",
                "severidad": "ALTA",
                "mensaje": f"Caída de asistencia: {ultimo} vs promedio {int(promedio)} (-{int((promedio-ultimo)/promedio*100)}%)",
                "recomendacion": "Revisar si hubo evento académico (paro/examen) o rotar menú",
            })

    # ------------- KPI 3: costo por ración -------------
    costos_altos = [c for c in cos if (c.get("costoBs") or 0) > PRESUPUESTO_BS_RACION]
    kpis["costoPromedioBsRacion"] = round(
        sum((c.get("costoBs") or 0) for c in cos) / max(1, len(cos)), 2
    )
    kpis["racionesSobrepresupuesto"] = len(costos_altos)
    for c in costos_altos:
        hallazgos.append({
            "tipo": "costo",
            "severidad": "MEDIA",
            "mensaje": f"Plato '{c.get('plato_id','?')}' costó {c['costoBs']} Bs (> {PRESUPUESTO_BS_RACION} Bs objetivo)",
            "recomendacion": "Negociar insumo con proveedor o cambiar proteína por alternativa económica",
        })

    # ------------- Resumen ejecutivo (reporte diario) -------------
    severidades = [h["severidad"] for h in hallazgos]
    hay_alta = "ALTA" in severidades
    resumen = (
        f"Resumen del {hoy.isoformat()}: {len(hallazgos)} hallazgo(s). "
        + ("Hay alertas de severidad ALTA — se recomienda revisar hoy mismo." if hay_alta
           else ("Hay alertas MEDIAS para revisar esta semana." if hallazgos
                 else "Todo en rango normal, sin alertas."))
    )

    return {
        "agente": "monitor-comedor",
        "objetivo": objetivo,
        "fecha": hoy.isoformat(),
        "kpis": kpis,
        "hallazgos": hallazgos,
        "cocinarHoy": cocinar_hoy,
        "resumenEjecutivo": resumen,
        "destinatario": "administrador",
        "requiere_confirmacion_humana": False,
    }
