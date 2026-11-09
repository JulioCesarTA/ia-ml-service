"""Cliente MCP (Model Context Protocol) por HTTP: así los agentes usan las herramientas de los otros microservicios.

Cada microservicio expone POST /mcp (JSON-RPC 2.0). El cliente hace el saludo una vez (initialize +
notifications/initialized) y luego llama `tools/call`. Los agentes nunca hacen SQL ni conocen las rutas REST.
"""
import itertools
import threading

import httpx

from app.data import comedor_http

VERSION = "2025-06-18"


class ErrorMcp(Exception):
    """El servidor no respondió, respondió un error JSON-RPC o la herramienta falló (isError)."""


class ClienteMcp:
    def __init__(self, servicio: str, espera: float = 15):
        self.servicio = servicio
        self.espera = espera
        self._ids = itertools.count(1)
        self._listo = False
        self._cabeceras = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"{comedor_http.url(self.servicio)}/mcp"

    def _enviar(self, mensaje: dict) -> dict | None:
        try:
            r = httpx.post(self.url, json=mensaje, headers=self._cabeceras, timeout=self.espera)
        except httpx.HTTPError as e:
            raise ErrorMcp(f"{self.servicio}: sin respuesta del servidor MCP ({type(e).__name__})") from e
        if r.status_code == 202:
            return None
        if r.status_code >= 400:
            raise ErrorMcp(f"{self.servicio}: el servidor MCP respondió {r.status_code}")
        if "mcp-session-id" in r.headers:
            self._cabeceras["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        datos = r.json()
        if "error" in datos:
            raise ErrorMcp(f"{self.servicio}: {datos['error'].get('message')}")
        return datos.get("result")

    def _rpc(self, metodo: str, params: dict | None = None) -> dict:
        return self._enviar({"jsonrpc": "2.0", "id": next(self._ids), "method": metodo, "params": params or {}})

    def _iniciar(self) -> None:
        with self._lock:
            if self._listo:
                return
            r = self._rpc("initialize", {"protocolVersion": VERSION, "capabilities": {},
                                         "clientInfo": {"name": "ia-ml-service", "version": "1.0.0"}})
            self._cabeceras["MCP-Protocol-Version"] = r.get("protocolVersion", VERSION)
            self._enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._listo = True

    def herramientas(self) -> list[dict]:
        self._iniciar()
        return self._rpc("tools/list")["tools"]

    def llamar(self, herramienta: str, **argumentos):
        """Ejecuta una herramienta y devuelve su resultado. Lanza ErrorMcp si falla."""
        self._iniciar()
        try:
            r = self._rpc("tools/call", {"name": herramienta, "arguments": argumentos})
        except ErrorMcp:
            self._listo = False          # el servidor pudo reiniciarse: la próxima vez se vuelve a saludar
            raise
        if r.get("isError"):
            raise ErrorMcp(f"{herramienta}: " + " ".join(c.get("text", "") for c in r.get("content", [])))
        return (r.get("structuredContent") or {}).get("resultado")


_clientes: dict[str, ClienteMcp] = {}


def cliente(servicio: str) -> ClienteMcp:
    """Un cliente por microservicio («menu», «comensales», «pagos»), compartido por todos los agentes."""
    if servicio not in _clientes:
        _clientes[servicio] = ClienteMcp(servicio)
    return _clientes[servicio]
