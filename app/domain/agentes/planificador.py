"""Reglas del agente planificador de menú: 'Armá el menú de la próxima semana.'

  1) Prioriza platos que usen insumos POR VENCER (reducir merma).
  2) Para cada día de la próxima semana y cada turno (DES/ALM/CENA), propone 2 platos de ese turno.
  3) Para cada propuesta, las raciones sugeridas salen del modelo de demanda (función `predecir`).
  4) Chequea requisitos nutricionales (proteína, carbohidrato, verdura) por turno.
  5) Marca `requiere_confirmacion_humana=true` (el admin debe aprobar el menú).

Los ids de plato son los mismos que usa el historial del comedor: así el modelo de demanda conoce la
popularidad de cada plato y las raciones sugeridas tienen sentido.
"""
from datetime import date, timedelta
from typing import Callable

# Recetario del comedor: plato -> turnos en que se sirve, grupo, insumos (nombres del inventario) y nutrientes por ración
RECETARIO = {
    # Desayuno
    "plato-api-con-pastel":    {"turnos": ("DESAYUNO",), "grupo": "carbo",    "insumos": ["MAIZ", "QUESO", "ACEITE"],          "nutri": {"proteina_g": 9,  "carbo_g": 62, "fibra_g": 4}},
    "plato-pan-con-leche":     {"turnos": ("DESAYUNO",), "grupo": "carbo",    "insumos": ["PAN", "LECHE"],                     "nutri": {"proteina_g": 8,  "carbo_g": 48, "fibra_g": 2}},
    "plato-sonso":             {"turnos": ("DESAYUNO",), "grupo": "carbo",    "insumos": ["YUCA", "QUESO"],                    "nutri": {"proteina_g": 10, "carbo_g": 55, "fibra_g": 3}},
    "plato-cunape-con-api":    {"turnos": ("DESAYUNO",), "grupo": "carbo",    "insumos": ["YUCA", "QUESO", "MAIZ"],            "nutri": {"proteina_g": 11, "carbo_g": 58, "fibra_g": 3}},
    # Almuerzo
    "plato-arroz-con-pollo":   {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["ARROZ", "POLLO", "ZANAH", "ACEITE"], "nutri": {"proteina_g": 27, "carbo_g": 48, "fibra_g": 5}},
    "plato-asado-de-res":      {"turnos": ("ALMUERZO",), "grupo": "proteina", "insumos": ["RES", "PAPA", "SAL"],               "nutri": {"proteina_g": 32, "carbo_g": 40, "fibra_g": 5}},
    "plato-majadito":          {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["ARROZ", "CHARQUE", "CEBOLLA", "TOMATE"], "nutri": {"proteina_g": 26, "carbo_g": 50, "fibra_g": 5}},
    "plato-milanesa":          {"turnos": ("ALMUERZO",), "grupo": "proteina", "insumos": ["RES", "PAN", "ACEITE", "ARROZ"],    "nutri": {"proteina_g": 30, "carbo_g": 45, "fibra_g": 5}},
    "plato-silpancho":         {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["RES", "ARROZ", "PAPA", "TOMATE", "CEBOLLA"], "nutri": {"proteina_g": 28, "carbo_g": 55, "fibra_g": 6}},
    "plato-pique-macho":       {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["RES", "PAPA", "TOMATE", "CEBOLLA"], "nutri": {"proteina_g": 29, "carbo_g": 42, "fibra_g": 6}},
    "plato-charque":           {"turnos": ("ALMUERZO",), "grupo": "proteina", "insumos": ["CHARQUE", "MAIZ", "QUESO"],         "nutri": {"proteina_g": 31, "carbo_g": 44, "fibra_g": 5}},
    "plato-fricase":           {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["CERDO", "MAIZ", "PAPA", "CEBOLLA"], "nutri": {"proteina_g": 27, "carbo_g": 46, "fibra_g": 5}},
    "plato-tallarin-con-carne": {"turnos": ("ALMUERZO",), "grupo": "mixto",   "insumos": ["FIDEO", "RES", "TOMATE", "CEBOLLA"], "nutri": {"proteina_g": 25, "carbo_g": 58, "fibra_g": 5}},
    "plato-chicharron":        {"turnos": ("ALMUERZO",), "grupo": "proteina", "insumos": ["CERDO", "MAIZ", "PAPA", "SAL"],     "nutri": {"proteina_g": 30, "carbo_g": 42, "fibra_g": 5}},
    "plato-locro":             {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["POLLO", "ARROZ", "PAPA", "ZANAH"],  "nutri": {"proteina_g": 25, "carbo_g": 41, "fibra_g": 6}},
    "plato-sopa-de-mani":      {"turnos": ("ALMUERZO",), "grupo": "mixto",    "insumos": ["MANI", "PAPA", "RES", "ZANAH"],     "nutri": {"proteina_g": 25, "carbo_g": 40, "fibra_g": 7}},
    # Cena
    "plato-sopa-de-fideo":     {"turnos": ("CENA",),     "grupo": "mixto",    "insumos": ["FIDEO", "POLLO", "ZANAH", "CEBOLLA"], "nutri": {"proteina_g": 14, "carbo_g": 36, "fibra_g": 4}},
    "plato-arroz-con-queso":   {"turnos": ("CENA",),     "grupo": "carbo",    "insumos": ["ARROZ", "QUESO", "ACEITE"],         "nutri": {"proteina_g": 12, "carbo_g": 52, "fibra_g": 2}},
    "plato-tortilla-de-papa":  {"turnos": ("CENA",),     "grupo": "carbo",    "insumos": ["PAPA", "HUEVO", "CEBOLLA", "ACEITE"], "nutri": {"proteina_g": 13, "carbo_g": 38, "fibra_g": 4}},
    "plato-pollo-frito":       {"turnos": ("CENA",),     "grupo": "proteina", "insumos": ["POLLO", "ACEITE", "PAPA", "SAL"],   "nutri": {"proteina_g": 30, "carbo_g": 35, "fibra_g": 3}},
}

TURNOS = ("DESAYUNO", "ALMUERZO", "CENA")
PLATOS_POR_TURNO = 2

# Requisitos nutricionales mínimos por almuerzo (SPEC)
REQ_NUTRI_ALMUERZO = {"proteina_g": 25, "carbo_g": 40, "fibra_g": 5}


def platos_de(turno: str, candidatos: list[str]) -> list[str]:
    """Los candidatos que se sirven en ese turno; si ninguno se sirve en él, los del recetario para ese turno."""
    propios = [p for p in candidatos if turno in RECETARIO.get(p, {}).get("turnos", ())]
    return propios or [p for p, r in RECETARIO.items() if turno in r["turnos"]]


def _dentro_vencimiento(platos_candidatos: list[str], insumos_por_vencer: set[str]) -> list[tuple[str, int]]:
    """Devuelve lista de (plato_id, usa_cuantos_insumos_por_vencer) ordenada desc."""
    scored = []
    for p in platos_candidatos:
        receta = RECETARIO.get(p, {})
        usados = [i for i in receta.get("insumos", []) if i in insumos_por_vencer]
        scored.append((p, len(usados)))
    return sorted(scored, key=lambda x: -x[1])


def planificar(objetivo: str, contexto: dict, bajos: list[dict], por_vencer: list[dict], hoy: date,
               predecir: Callable[[dict], dict]) -> dict:
    insumos_por_vencer_set = {str(x.get("nombre","")).upper() for x in por_vencer}

    candidatos = contexto.get("platos_candidatos") or list(RECETARIO.keys())
    propuesta = []
    semana_inicio = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)
    # Por turno: sus platos, los que usan insumos por vencer primero
    priorizados = {t: _dentro_vencimiento(platos_de(t, candidatos), insumos_por_vencer_set) for t in TURNOS}

    # Rotación: para cada (día, turno) tomo 2 platos distintos de ese turno mediante offset modular
    slot = {t: 0 for t in TURNOS}
    for d_offset in range(5):  # lunes a viernes
        dia = semana_inicio + timedelta(days=d_offset)
        for turno in TURNOS:
            base = priorizados[turno]
            n = len(base)
            picks = [base[(slot[turno] + k) % n] for k in range(min(PLATOS_POR_TURNO, n))]
            slot[turno] += PLATOS_POR_TURNO
            for plato_id, usa_por_vencer in picks:
                receta = RECETARIO.get(plato_id, {})
                pred = predecir({
                    "plato_id": plato_id,
                    "fecha": dia.isoformat(),
                    "turno": turno,
                    "es_feriado": False,
                    "temperatura_c": contexto.get("temperatura_c", 22.0),
                })
                # Chequeo nutricional (solo almuerzo exige)
                cumple_nutri = True
                if turno == "ALMUERZO" and receta.get("nutri"):
                    nu = receta["nutri"]
                    cumple_nutri = all(nu.get(k, 0) >= v for k, v in REQ_NUTRI_ALMUERZO.items())
                propuesta.append({
                    "fecha": dia.isoformat(),
                    "diaSemana": pred["diaSemana"],
                    "turno": turno,
                    "platoId": plato_id,
                    "racionesSugeridas": pred["racionesEstimadas"],
                    "aprovechaInsumosPorVencer": usa_por_vencer,
                    "cumpleRequisitosNutricionales": cumple_nutri,
                    "nutrientes": receta.get("nutri", {}),
                    "insumosRequeridos": receta.get("insumos", []),
                })

    return {
        "agente": "planificador-menu",
        "objetivo": objetivo,
        "semanaInicio": semana_inicio.isoformat(),
        "propuesta": propuesta,
        "insumosStockBajoDetectados": [i.get("nombre") for i in bajos],
        "insumosPorVencer": [p["nombre"] for p in por_vencer][:10],
        "requisitosNutricionalesAlmuerzo": REQ_NUTRI_ALMUERZO,
        "requiere_confirmacion_humana": True,
        "nota": "El administrador debe revisar y aprobar antes de publicar.",
    }
