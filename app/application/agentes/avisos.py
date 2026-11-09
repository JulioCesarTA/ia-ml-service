"""Convierte lo que calculan los agentes en propuestas para el administrador (panel + Telegram + push)."""
from app.application.cola_mensajes import ColaMensajes
from app.application.propuestas import ServicioPropuestas
from app.application.push import ServicioPush
from app.domain import propuestas as dom_propuestas
from app.domain.agentes import avisos as dom
from app.domain.agentes.avisos import ROLES_ADMIN, ROLES_INVENTARIO


class ServicioAvisos:
    def __init__(self, propuestas: ServicioPropuestas, push: ServicioPush, cola: ColaMensajes):
        self.propuestas = propuestas
        self.push = push
        self.cola = cola

    def _push(self, roles: list[str], titulo: str, cuerpo: str, datos: dict) -> None:
        """Aviso al celular. Es «lo mejor posible»: nunca detiene al agente (Telegram y el panel siguen avisando)."""
        try:
            self.push.enviar_a_roles(roles, titulo, cuerpo, datos)
        except Exception:
            pass

    def _publicar(self, p: dict, nueva: bool, texto: str) -> dict:
        if nueva:
            self.cola.encolar(texto, p["id"])
        return {"id": p["id"], "estado": p["estado"], "nueva": nueva}

    def proponer_inventario(self, r: dict, forzar: bool = False) -> dict | None:
        if not (r.get("requiereAviso") and r.get("ordenesBorrador")):
            if forzar:                                       # el administrador pulsó «Ejecutar»: que sepa que no hay nada que comprar
                self._push(ROLES_ADMIN, "Inventario y compras", "Sin alertas: no hay stock bajo ni lotes por vencer que requieran compra.", {"tipo": "inventario"})
            return None
        p, nueva = self.propuestas.registrar(
            "compra", r["claveAlerta"], f"Orden de compra ({r['severidad']}): {len(r['ordenesBorrador'])} insumos, {r['totalBorradorBs']} Bs",
            r["mensajeAdmin"], r, forzar=forzar)
        if nueva:
            if not self._push_inventario(r, p["id"]):           # sin detalle de insumos: igual se avisa al administrador
                self._push(ROLES_ADMIN, "Inventario: orden de compra propuesta", f"{len(r['ordenesBorrador'])} insumos, {r['totalBorradorBs']} Bs. Revísala y apruébala.",
                           {"tipo": "propuesta", "propuesta": p["id"]})
        return self._publicar(p, nueva, r["mensajeAdmin"])

    def _push_inventario(self, r: dict, propuesta_id: str) -> bool:
        """Stock bajo o lotes por vencer: aviso al celular del administrador y de cocina. Devuelve si había algo que avisar."""
        try:
            partes = dom.partes_inventario(r)
            if not partes:
                return False
            self.push.enviar_a_roles(ROLES_INVENTARIO, f"Inventario: alerta {r['severidad']}", ". ".join(partes) + ".",
                                     {"tipo": "stock_bajo", "propuesta": propuesta_id})
            return True
        except Exception:
            return False

    def proponer_menu(self, r: dict, forzar: bool = False) -> dict:
        texto = dom.texto_menu(r)
        p, nueva = self.propuestas.registrar("menu", f"menu:{r['semanaInicio']}", f"Menú de la semana del {r['semanaInicio']}",
                                             texto, r, forzar=forzar)
        if nueva:
            self._push(ROLES_ADMIN, "Menú propuesto", f"Semana del {r['semanaInicio']}: {len(r['propuesta'])} platos. Revísalo y apruébalo.",
                       {"tipo": "propuesta", "propuesta": p["id"]})
        return self._publicar(p, nueva, texto)

    def avisar_monitor(self, r: dict, forzar: bool = False) -> dict | None:
        if not r.get("hallazgos"):
            if forzar:                                       # el administrador pulsó «Ejecutar»: que sepa que no hay novedades
                self._push(ROLES_ADMIN, "Monitor del comedor", "Sin novedades: no se detectó ningún problema.", {"tipo": "monitor"})
            return None
        texto = dom.texto_monitor(r)
        clave = dom.clave_monitor(r)
        p, nueva = self.propuestas.registrar("info", clave, "Informe del monitor", texto, {}, forzar=forzar, informativa=True)
        if nueva:
            self.cola.encolar(texto)
            n = len(r["hallazgos"])
            self._push(ROLES_ADMIN, "Monitor del comedor", f"{n} hallazgo{'s' if n != 1 else ''}: {r['resumenEjecutivo']}"[:300],
                       {"tipo": "monitor", "propuesta": p["id"]})
        return {"id": p["id"], "estado": p["estado"], "nueva": nueva}

    # ----------------------------- decisiones desde el panel -----------------------------

    def avisar_resultado(self, p: dict) -> None:
        """Cuando se decide desde el panel, Telegram también se entera del resultado."""
        self.cola.encolar(dom_propuestas.texto_resultado(p))

    def decidir_desde_panel(self, pid: str, aprobar: bool) -> dict | None:
        """Aprueba o rechaza desde el panel. None si la propuesta no existe."""
        antes = self.propuestas.obtener(pid)
        p = self.propuestas.resolver(pid, aprobar, "panel")
        if p is not None and antes and antes["estado"] == dom_propuestas.PENDIENTE:
            self.avisar_resultado(p)
        return p

    def sincronizar(self, items: list[dict]) -> list[dict]:
        """Recibe lo que el navegador generó/decidió sin conexión: lo registra, avisa a Telegram y ejecuta lo aprobado."""
        salida = []
        for it in items:
            if it["tipo"] not in dom.TIPOS_SINCRONIZABLES:
                continue
            p, nueva = self.propuestas.registrar(it["tipo"], it["clave"], it["titulo"], it["resumen"], it["payload"],
                                                 informativa=it["tipo"] == "info")
            if nueva:
                self.cola.encolar(it["resumen"], None if it["tipo"] == "info" else p["id"])
                self._push(ROLES_ADMIN, it["titulo"][:100], "Generado sin conexión y ya sincronizado. Revísalo en el panel.",
                           {"tipo": "propuesta", "propuesta": p["id"]})
            if it.get("decision") and p["estado"] == dom_propuestas.PENDIENTE:
                p = self.propuestas.resolver(p["id"], it["decision"] == "aprobar", "panel (decidido sin conexión)")
                self.avisar_resultado(p)
            salida.append({"clave": it["clave"], "id": p["id"], "estado": p["estado"]})
        return salida
