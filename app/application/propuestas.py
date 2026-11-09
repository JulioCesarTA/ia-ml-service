"""Propuestas de los agentes que requieren aprobación del administrador.

Se guardan en la base local (sin internet). Al aprobar una propuesta se ejecuta su acción:
  - menu:   publica los menús propuestos en menu-inventario-service, por MCP.
  - compra: n8n registra la obligación de pago por proveedor en pagos-tickets-service (SPEC §9, flujo 2).
"""
from app.application.cola_mensajes import ColaMensajes
from app.application.ports.externos import HerramientasMcp, MotorFlujos
from app.application.ports.repositorios import RepositorioPropuestas
from app.domain import propuestas as dom


class ServicioPropuestas:
    def __init__(self, repo: RepositorioPropuestas, mcp: HerramientasMcp, flujos: MotorFlujos, cola: ColaMensajes,
                 ventana_s: int = dom.VENTANA_S_DEFECTO):
        self._repo = repo
        self._mcp = mcp
        self._flujos = flujos
        self._cola = cola
        self.ventana_s = ventana_s

    def obtener(self, pid: str) -> dict | None:
        return self._repo.obtener(pid)

    def listar(self, estado: str | None = None, limite: int = 30) -> list[dict]:
        return self._repo.listar(estado, limite)

    def registrar(self, tipo: str, clave: str, titulo: str, resumen: str, payload: dict,
                  forzar: bool = False, informativa: bool = False) -> tuple[dict, bool]:
        """Crea la propuesta. Devuelve (propuesta, es_nueva). No repite la misma alerta dentro de la ventana."""
        return self._repo.crear_si_no_hay_vigente(tipo, clave, titulo, resumen, payload, forzar, informativa, self.ventana_s)

    def resolver(self, pid: str, aprobar: bool, canal: str = "panel") -> dict | None:
        """Aprueba (y ejecuta) o rechaza. Solo actúa si sigue PENDIENTE; si no, devuelve el estado actual."""
        if not self._repo.tomar_pendiente(pid, dom.EJECUTANDO if aprobar else dom.RECHAZADA,
                                          None if aprobar else f"Rechazada desde {canal}"):
            return self.obtener(pid)
        p = self.obtener(pid)
        if p is None or not aprobar:
            return p
        try:
            if p["tipo"] == "compra":
                resultado, ok = self._ejecutar_compra(p["payload"], pid)
            else:
                resultado, ok = self._ejecutar_menu(p["payload"])
        except Exception as e:  # el administrador ve el error y puede reintentar con una propuesta nueva
            resultado, ok = f"No se pudo ejecutar: {e}", False
        self._repo.cerrar(pid, dom.EJECUTADA if ok else dom.ERROR, f"{resultado} (aprobada desde {canal})")
        return self.obtener(pid)

    # ----------------------------- ejecutores -----------------------------

    def _ejecutar_menu(self, payload: dict) -> tuple[str, bool]:
        grupos = dom.menus_a_publicar(payload)
        publicados = omitidos = fallidos = 0
        existentes = {turno: {m.get("fecha") for m in self._mcp.consultar_menu(turno)} for turno in {t for _, t in grupos}}
        for (fecha, turno), platos in sorted(grupos.items()):
            if fecha in existentes.get(turno, set()):
                omitidos += 1
                continue
            if self._mcp.publicar_menu(fecha, turno, platos):
                publicados += 1
            else:
                fallidos += 1
        return dom.resultado_publicacion(publicados, omitidos, fallidos)

    def _ejecutar_compra(self, payload: dict, pid: str) -> tuple[str, bool]:
        ordenes = payload.get("ordenesBorrador", [])
        if not ordenes:
            return "No había líneas de compra", False
        grupos = dom.por_proveedor(ordenes)
        if self._flujos.activo():
            self._flujos.llamar("orden-aprobada", dom.cuerpo_orden_aprobada(pid, grupos), 30)
        self._cola.encolar(dom.texto_orden_aprobada(payload, grupos))
        return f"Orden aprobada: {len(ordenes)} insumos, {payload.get('totalBorradorBs', 0)} Bs", True
