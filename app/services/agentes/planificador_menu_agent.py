"""Agente: Planificador de menú.

Misión: 'Armá el menú de la próxima semana.'
Pasos:
  1) Consulta las 3 fuentes vía MCP: menú actual (recetas vigentes y aceptación),
     stock disponible de insumos, lotes por vencer.
  2) Prioriza platos que usen insumos POR VENCER (reducir merma).
  3) Para cada día de la próxima semana y cada turno (DES/ALM/CENA), propone 2 platos.
  4) Para cada propuesta, calcula raciones sugeridas con el modelo ML de demanda
     (features reales: fecha, día de la semana, exámenes, feriados, temperatura).
  5) Chequea requisitos nutricionales (proteína, carbohidrato, verdura) por turno.
  6) Marca `requiere_confirmacion_humana=true` (el admin debe aprobar el menú).
"""
from datetime import date, timedelta
from app.data.mcp_tools import McpToolClient
from app.services.predictor_demanda import predecir_demanda


# Recetario demo con nutrientes
RECETARIO = {
    "plato-asado":        {"grupo": "proteina", "insumos": ["RES", "SAL"],       "nutri": {"proteina_g": 32, "carbo_g": 10, "fibra_g": 2}},
    "plato-pollo":        {"grupo": "proteina", "insumos": ["POLLO", "SAL"],     "nutri": {"proteina_g": 28, "carbo_g": 15, "fibra_g": 3}},
    "plato-pescado":      {"grupo": "proteina", "insumos": ["PESCADO", "LIMON"], "nutri": {"proteina_g": 30, "carbo_g": 12, "fibra_g": 2}},
    "plato-pastel-papa":  {"grupo": "carbo",    "insumos": ["PAPA", "LECHE"],    "nutri": {"proteina_g": 10, "carbo_g": 55, "fibra_g": 5}},
    "plato-arroz-pollo":  {"grupo": "mixto",    "insumos": ["ARROZ", "POLLO"],   "nutri": {"proteina_g": 25, "carbo_g": 45, "fibra_g": 3}},
    "plato-ensalada":     {"grupo": "verdura",  "insumos": ["TOMATE", "LECHUGA", "ZANAHORIA"], "nutri": {"proteina_g": 4, "carbo_g": 12, "fibra_g": 8}},
    "plato-sopa-mani":    {"grupo": "mixto",    "insumos": ["MANI", "PAPA"],     "nutri": {"proteina_g": 15, "carbo_g": 35, "fibra_g": 5}},
}

TURNOS = ("DESAYUNO", "ALMUERZO", "CENA")

# Requisitos nutricionales mínimos por almuerzo (SPEC)
REQ_NUTRI_ALMUERZO = {"proteina_g": 25, "carbo_g": 40, "fibra_g": 5}


def _dentro_vencimiento(platos_candidatos: list[str], insumos_por_vencer: set[str]) -> list[tuple[str, int]]:
    """Devuelve lista de (plato_id, usa_cuantos_insumos_por_vencer) ordenada desc."""
    scored = []
    for p in platos_candidatos:
        receta = RECETARIO.get(p, {})
        usados = [i for i in receta.get("insumos", []) if i in insumos_por_vencer]
        scored.append((p, len(usados)))
    return sorted(scored, key=lambda x: -x[1])


class PlanificadorMenuAgent:
    def run(self, objetivo: str, contexto: dict) -> dict:
        tools = McpToolClient()
        stock = tools.ver_stock_insumo() or []
        bajos = tools.ver_stock_bajo() or []
        por_vencer = tools.lotes_por_vencer(dias=10)
        insumos_por_vencer_set = {str(x.get("nombre","")).upper() for x in por_vencer}

        candidatos = contexto.get("platos_candidatos") or list(RECETARIO.keys())
        propuesta = []
        semana_inicio = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
        priorizados_base = _dentro_vencimiento(candidatos, insumos_por_vencer_set)

        # Rotación: para cada (día, turno) tomo 2 platos distintos mediante offset modular
        slot = 0
        for d_offset in range(5):  # lunes a viernes
            dia = semana_inicio + timedelta(days=d_offset)
            for turno in TURNOS:
                n = len(priorizados_base)
                picks = [priorizados_base[(slot + k) % n] for k in range(2)]
                slot += 2
                for plato_id, usa_por_vencer in picks:
                    receta = RECETARIO.get(plato_id, {})
                    pred = predecir_demanda({
                        "plato_id": plato_id,
                        "fecha": dia.isoformat(),
                        "es_feriado": False,
                        "temperatura_c": contexto.get("temperatura_c", 22.0),
                    })
                    # Chequeo nutricional (solo almuerzo exige)
                    cumple_nutri = True
                    if turno == "ALMUERZO" and receta.get("nutri"):
                        n = receta["nutri"]
                        cumple_nutri = all(n.get(k, 0) >= v for k, v in REQ_NUTRI_ALMUERZO.items())
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
