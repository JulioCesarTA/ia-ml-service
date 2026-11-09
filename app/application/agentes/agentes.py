"""Los 3 agentes de IA (SPEC §3.4): cada uno pide sus datos por los puertos (MCP, CQRS, modelo de demanda) y aplica
las reglas del dominio. No hacen SQL ni conocen rutas REST."""
from datetime import date
from typing import Callable

from app.application.ports.externos import ConsultasLectura, HerramientasMcp
from app.domain.agentes import inventario, monitor, planificador


class InventarioComprasAgent:
    """Misión: 'Que nunca falte un insumo ni se venza nada.'"""

    def __init__(self, mcp: HerramientasMcp):
        self._mcp = mcp

    def run(self, objetivo: str, contexto: dict) -> dict:
        borrador = self._mcp.crear_orden_compra_borrador() or []
        por_vencer = self._mcp.lotes_por_vencer(dias=inventario.DIAS_VENCIMIENTO)
        return inventario.evaluar(objetivo, borrador, por_vencer, date.today())


class MonitorComedorAgent:
    """Misión: 'Monitoreame el comedor y avisame lo importante.'"""

    def __init__(self, consultas: ConsultasLectura, mcp: HerramientasMcp):
        self._consultas = consultas
        self._mcp = mcp

    def _consulta(self, indicador: str, hoy: date) -> list[dict]:
        nombre, dias = monitor.CONSULTAS[indicador]
        try:
            return self._consultas.consulta_predefinida(nombre, monitor.rango(hoy, dias)) or []
        except Exception:
            return []

    def run(self, objetivo: str, contexto: dict) -> dict:
        hoy = date.today()
        desp = self._consulta("desperdicio", hoy)
        asist = self._consulta("asistencia", hoy)
        cos = self._consulta("costo", hoy)
        cocinar_hoy = {t: self._mcp.sugerir_cantidad_cocinar(t) for t in monitor.TURNOS}
        return monitor.evaluar(objetivo, hoy, desp, asist, cos, cocinar_hoy)


class PlanificadorMenuAgent:
    """Misión: 'Armá el menú de la próxima semana.' Consulta por MCP stock bajo y lotes por vencer."""

    def __init__(self, mcp: HerramientasMcp, predecir_demanda: Callable[[dict], dict]):
        self._mcp = mcp
        self._predecir = predecir_demanda

    def run(self, objetivo: str, contexto: dict) -> dict:
        bajos = self._mcp.ver_stock_bajo() or []
        por_vencer = self._mcp.lotes_por_vencer(dias=10)
        return planificador.planificar(objetivo, contexto, bajos, por_vencer, date.today(), self._predecir)
