"""Herramientas (tools) que los agentes usan para leer los demás microservicios, por MCP (ver mcp_cliente).

Los agentes NO hacen SQL ni llaman rutas REST: piden la herramienta por su nombre al servidor MCP del microservicio
dueño del dato. Si el servicio no responde, la herramienta devuelve vacío y el agente sigue con lo que tiene.
"""
from app.data.mcp_cliente import ErrorMcp, cliente


def _o_vacio(servicio: str, herramienta: str, defecto, **args):
    try:
        r = cliente(servicio).llamar(herramienta, **args)
        return defecto if r is None else r
    except ErrorMcp:
        return defecto


class McpToolClient:
    # --- menu-inventario-service ---
    def consultar_menu(self, turno: str) -> list:
        return _o_vacio("menu", "consultar_menu", [], turno=turno)

    def ver_stock_insumo(self) -> list:
        return _o_vacio("menu", "ver_stock_insumo", [])

    def ver_stock_bajo(self) -> list:
        return _o_vacio("menu", "ver_stock_bajo", [])

    def lotes_por_vencer(self, dias: int = 7) -> list:
        """Lotes que vencen en `dias` días o menos: {insumoId, nombre, cantidad, unidad, vence, diasRestantes}."""
        return _o_vacio("menu", "lotes_por_vencer", [], dias=dias)

    # --- comensales-reservas-service ---
    def consultar_beca(self, estudiante: str) -> dict:
        return _o_vacio("comensales", "consultar_beca", {}, estudianteId=estudiante)
