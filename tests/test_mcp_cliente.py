"""Los agentes usan las herramientas de los otros microservicios por MCP (JSON-RPC 2.0 en POST /mcp)."""
import httpx
import pytest

from app.infrastructure.adapters.outbound.http import mcp_cliente
from app.infrastructure.adapters.outbound.http.mcp_herramientas import McpToolClient


class ServidorFalso:
    """Imita el servidor MCP de un microservicio y anota lo que recibe."""

    def __init__(self, falla_herramienta=False):
        self.recibidos = []
        self.falla_herramienta = falla_herramienta

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.recibidos.append((url, json, dict(headers or {})))
        req = httpx.Request("POST", url)
        if "id" not in json:
            return httpx.Response(202, request=req)
        m = json["method"]
        if m == "initialize":
            res = {"protocolVersion": json["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "x"}}
        elif m == "tools/call" and self.falla_herramienta:
            res = {"content": [{"type": "text", "text": "Falta el argumento «turno»"}], "isError": True}
        elif m == "tools/call":
            res = {"content": [{"type": "text", "text": "[]"}], "isError": False,
                   "structuredContent": {"resultado": [{"herramienta": json["params"]["name"], "args": json["params"]["arguments"]}]}}
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": json["id"], "error": {"code": -32601, "message": "no"}}, request=req)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": json["id"], "result": res}, request=req)


@pytest.fixture(autouse=True)
def clientes_nuevos(monkeypatch):
    monkeypatch.setattr(mcp_cliente, "_clientes", {})
    monkeypatch.setenv("MENU_URL", "http://menu:8080")


def test_saluda_una_vez_y_luego_llama_herramientas(monkeypatch):
    srv = ServidorFalso()
    monkeypatch.setattr(mcp_cliente.httpx, "post", srv)
    t = McpToolClient()
    assert t.lotes_por_vencer(dias=10) == [{"herramienta": "lotes_por_vencer", "args": {"dias": 10}}]
    t.ver_stock_bajo()
    metodos = [j.get("method") for _, j, _ in srv.recibidos]
    assert metodos == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    assert all(u == "http://menu:8080/mcp" for u, _, _ in srv.recibidos)
    assert srv.recibidos[-1][2]["MCP-Protocol-Version"] == mcp_cliente.VERSION


def test_error_de_la_herramienta_se_informa(monkeypatch):
    monkeypatch.setattr(mcp_cliente.httpx, "post", ServidorFalso(falla_herramienta=True))
    with pytest.raises(mcp_cliente.ErrorMcp, match="turno"):
        mcp_cliente.cliente("menu").llamar("consultar_menu")


def test_sin_servidor_el_agente_sigue_con_vacio(monkeypatch):
    def caido(*a, **k):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(mcp_cliente.httpx, "post", caido)
    assert McpToolClient().ver_stock_insumo() == []
    assert McpToolClient().consultar_beca("e1") == {}
