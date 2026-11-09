"""3 agentes de IA (SPEC §3.4). Cada misión usa skills MCP contra los otros microservicios.
Las propuestas que requieren decisión llegan al administrador por Telegram y al panel."""
from fastapi import APIRouter, HTTPException

from app.application.agentes.agentes import InventarioComprasAgent, MonitorComedorAgent, PlanificadorMenuAgent
from app.application.agentes.avisos import ServicioAvisos
from app.application.agentes.paquete_offline import PaqueteOffline
from app.application.programador import Programador
from app.application.propuestas import ServicioPropuestas
from app.application.telegram_bot import ServicioTelegram
from app.infrastructure.adapters.inbound.http.esquemas.agentes import EventoTelegram, Horario, Mision, PropuestaLocal


def crear_router(inventario_agente: InventarioComprasAgent, planificador_agente: PlanificadorMenuAgent,
                 monitor_agente: MonitorComedorAgent, avisos: ServicioAvisos, propuestas: ServicioPropuestas,
                 telegram_bot: ServicioTelegram, paquete_offline: PaqueteOffline, programador: Programador) -> APIRouter:
    router = APIRouter()

    @router.post("/monitor-comedor")
    def monitor(m: Mision):
        r = monitor_agente.run(m.objetivo, m.contexto or {})
        r["aviso"] = avisos.avisar_monitor(r, forzar=True)     # «Ejecutar» del panel: siempre responde, aunque el hallazgo sea el mismo
        return r

    @router.post("/planificador-menu")
    def planif(m: Mision):
        r = planificador_agente.run(m.objetivo, m.contexto or {})
        r["propuestaMenu"] = avisos.proponer_menu(r, forzar=True)
        return r

    @router.post("/inventario-compras")
    def inv(m: Mision):
        r = inventario_agente.run(m.objetivo, m.contexto or {})
        # El flujo nocturno de n8n no fuerza: si la misma alerta sigue vigente, no la repite cada noche
        r["propuestaCompra"] = avisos.proponer_inventario(r, forzar=not (m.contexto or {}).get("automatico"))
        return r

    @router.get("/propuestas")
    def listar_propuestas(estado: str | None = None):
        return propuestas.listar(estado.upper() if estado else None)

    def _decidir(pid: str, aprobar: bool):
        p = avisos.decidir_desde_panel(pid, aprobar)
        if p is None:
            raise HTTPException(404, "Propuesta no encontrada")
        return p

    @router.post("/propuestas/{pid}/aprobar")
    def aprobar(pid: str):
        return _decidir(pid, True)

    @router.post("/propuestas/{pid}/rechazar")
    def rechazar(pid: str):
        return _decidir(pid, False)

    @router.get("/telegram")
    def telegram():
        return telegram_bot.estado()

    @router.post("/telegram/evento")
    def telegram_evento(evento: EventoTelegram):
        """n8n entrega cada mensaje o botón y ejecuta en Telegram las acciones que se devuelven."""
        return {"acciones": telegram_bot.procesar_evento(evento.model_dump(exclude_none=True))}

    # Modo sin conexión del navegador: el panel guarda este paquete y corre los 3 agentes
    # con él cuando no alcanza al servidor. Al volver la red sincroniza lo decidido.
    @router.get("/paquete-offline")
    def paquete():
        return paquete_offline.construir()

    @router.post("/propuestas/sincronizar")
    def sincronizar(items: list[PropuestaLocal]):
        return avisos.sincronizar([i.model_dump() for i in items])

    # Programación: cada cuánto / a qué hora corre cada agente solo (editable desde el panel)
    @router.get("/horarios")
    def horarios():
        return programador.estado()

    @router.put("/horarios/{agente}")
    def guardar_horario(agente: str, h: Horario):
        if agente not in programador.AGENTES:
            raise HTTPException(404, "Agente desconocido")
        try:
            programador.guardar(agente, h.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e))
        return programador.estado()[agente]

    return router
