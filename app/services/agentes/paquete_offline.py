"""Paquete para el modo sin conexión del navegador: stock, demanda prevista y constantes para que el panel
corra los 3 agentes sin alcanzar al servidor. Al volver la red, el panel sincroniza lo decidido."""
from datetime import date, timedelta

from app.data import cqrs_client
from app.data.mcp_tools import McpToolClient
from app.services.agentes.inventario_compras_agent import DIAS_VENCIMIENTO, PRECIO_BS, PROVEEDOR
from app.services.agentes.monitor_comedor_agent import (
    PRESUPUESTO_BS_RACION, UMBRAL_CAIDA_ASISTENCIA, UMBRAL_DESPERDICIO_ALERTA)
from app.services.agentes.planificador_menu_agent import RECETARIO, REQ_NUTRI_ALMUERZO
from app.services.predictor_demanda import predecir_demanda

DIAS_SEMANA = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]


def construir() -> dict:
    hoy = date.today()

    def consulta(nombre: str, dias: int):
        try:
            return cqrs_client.run_query_predefinida(nombre, {
                "desde": (hoy - timedelta(days=dias)).isoformat(), "hasta": hoy.isoformat()}) or []
        except Exception:
            return []

    fechas = [(hoy + timedelta(days=i)).isoformat() for i in range(1, 22)]
    demanda = {pl: {f: predecir_demanda({"plato_id": pl, "fecha": f, "es_feriado": False, "temperatura_c": 22.0})["racionesEstimadas"]
                    for f in fechas} for pl in RECETARIO}
    return {
        "generado": hoy.isoformat(),
        "insumos": McpToolClient().ver_stock_insumo() or [],
        "demanda": demanda,
        "constantes": {
            "proveedor": PROVEEDOR, "precioBs": PRECIO_BS, "diasVencimiento": DIAS_VENCIMIENTO,
            "recetario": RECETARIO, "reqNutriAlmuerzo": REQ_NUTRI_ALMUERZO, "diasSemana": DIAS_SEMANA,
            "presupuestoBsRacion": PRESUPUESTO_BS_RACION, "umbralDesperdicio": UMBRAL_DESPERDICIO_ALERTA,
            "umbralCaidaAsistencia": UMBRAL_CAIDA_ASISTENCIA,
        },
        "monitor": {"desperdicio": consulta("desperdicio_por_plato", 7),
                    "asistencia": consulta("asistencia_diaria", 14), "costo": consulta("costo_por_racion", 7)},
    }
