"""Saga Orchestrator — SPEC §5. Coordina menú, reservas y pagos; el estado y la idempotencia van al puerto AlmacenSagas.
Saga 1: reservar + apartar porción + cobrar + confirmar.
Saga 2: cancelar (devolver pago -> liberar porción -> cancelar reserva)."""
import uuid

from app.application.ports.comedor import ServicioMenu, ServicioPagos, ServicioReservas
from app.application.ports.sagas import AlmacenSagas
from app.domain import saga as dom
from app.domain.saga import COMPENSATED, COMPLETED, PENDING_PAYMENT, RESERVED


class SagaOrchestrator:

    def __init__(self, menu: ServicioMenu, reservas: ServicioReservas, pagos: ServicioPagos, almacen: AlmacenSagas):
        self._menu, self._reservas, self._pagos, self._almacen = menu, reservas, pagos, almacen
        try: self._almacen.asegurar_tablas()
        except Exception: pass

    def reservar_y_pagar(self, p: dict) -> dict:
        # Idempotencia
        cached = self._almacen.bloquear_idempotencia(p["idempotency_key"])
        if dom.es_reutilizable(cached): return cached

        saga_id = str(uuid.uuid4())
        estado = dom.nuevo_estado(saga_id, p)
        self._almacen.guardar_saga(saga_id, estado)

        try:
            # Paso 1: crear reserva pendiente
            reserva_id = self._reservas.crear_reserva(dom.datos_reserva(p, saga_id))
            estado.update(step=1, reservaId=reserva_id)
            estado["compensations"].append(dom.comp_cancelar_reserva(reserva_id))
            self._almacen.guardar_saga(saga_id, estado)

            # Paso 2: apartar porción
            self._menu.apartar_porcion(p["menu_id"], p["plato_id"])
            estado["step"] = 2
            estado["compensations"].append(dom.comp_liberar_porcion(p["menu_id"], p["plato_id"]))
            self._almacen.guardar_saga(saga_id, estado)

            # Paso 3: cobrar
            pago = self._pagos.cobrar(dom.datos_cobro(reserva_id, p, saga_id))
            estado.update(step=3, pagoId=pago["pagoId"], ticketId=pago["ticketId"])
            estado["compensations"].append(dom.comp_devolver_pago(pago["pagoId"]))
            self._almacen.guardar_saga(saga_id, estado)

            # Pago con QR/tarjeta: la reserva queda pendiente hasta que el pago se verifique.
            if pago.get("stripe"):
                estado.update(step=3, status=PENDING_PAYMENT)
                self._almacen.guardar_saga(saga_id, estado)
                out = dom.respuesta(saga_id, PENDING_PAYMENT, reserva_id, pago, qr=None, stripe=pago.get("stripe"))
                self._almacen.guardar_respuesta_idempotencia(p["idempotency_key"], out)
                return out

            # Paso 4: confirmar reserva + emitir QR (beca / efectivo)
            confirmada, conf = self._reservas.confirmar_reserva(reserva_id)
            if not confirmada:
                raise RuntimeError("No se pudo confirmar la reserva")
            estado.update(step=4, status=COMPLETED, qr=conf.get("qr"), finished_at=dom.ahora_iso())
            self._almacen.guardar_saga(saga_id, estado)

            out = dom.respuesta(saga_id, COMPLETED, reserva_id, pago, qr=conf.get("qr"), stripe=None)
            self._almacen.guardar_respuesta_idempotencia(p["idempotency_key"], out)
            return out

        except Exception as e:
            # Compensar en orden inverso
            self._compensar(estado)
            estado.update(status=COMPENSATED, error=str(e), finished_at=dom.ahora_iso())
            self._almacen.guardar_saga(saga_id, estado)
            raise

    # ----------------------------- reservar primero, pagar después -----------------------------

    def reservar(self, p: dict) -> dict:
        """Pasos 1 y 2 de la Saga 1 SIN cobrar: queda la reserva «pendiente» con su porción apartada.
        Con beca vigente que cubre la ración no hay nada que pagar: se completa todo (beca + confirmación + QR)."""
        cached = self._almacen.bloquear_idempotencia(p["idempotency_key"])
        if dom.es_reutilizable(cached):
            return cached
        beca = self._reservas.beca(p["estudiante_id"])
        if dom.beca_cubre(beca):
            out = self.reservar_y_pagar({**p, "metodo_pago": "beca", "monto": 0.0, "idempotency_key": f"{p['idempotency_key']}:beca"})
            self._almacen.guardar_respuesta_idempotencia(p["idempotency_key"], out)
            return out

        saga_id = str(uuid.uuid4())
        estado = dom.nuevo_estado(saga_id, p, tipo="reservar")
        self._almacen.guardar_saga(saga_id, estado)
        try:
            reserva_id = self._reservas.crear_reserva(dom.datos_reserva(p, saga_id))
            estado.update(step=1, reservaId=reserva_id)
            estado["compensations"].append(dom.comp_cancelar_reserva(reserva_id))
            self._menu.apartar_porcion(p["menu_id"], p["plato_id"])
            estado.update(step=2, status=RESERVED, finished_at=dom.ahora_iso())
            self._almacen.guardar_saga(saga_id, estado)
            out = dom.respuesta(saga_id, RESERVED, reserva_id, requierePago=True, qr=None, stripe=None)
            self._almacen.guardar_respuesta_idempotencia(p["idempotency_key"], out)
            return out
        except Exception as e:
            self._compensar(estado)
            estado.update(status=COMPENSATED, error=str(e), finished_at=dom.ahora_iso())
            self._almacen.guardar_saga(saga_id, estado)
            raise

    def pagar(self, p: dict) -> dict:
        """Paso 3 y 4 de una reserva pendiente: cobrar (QR bancario por Stripe o efectivo) y confirmar con su QR.
        Con QR/tarjeta queda PENDING_PAYMENT hasta que el pago se verifique (`confirmar_pago`)."""
        cached = self._almacen.bloquear_idempotencia(p["idempotency_key"])
        if dom.es_reutilizable(cached):
            return cached
        dom.validar_metodo_pago_diferido(p["metodo_pago"])
        r = self._reservas.obtener_reserva(p["reserva_id"])
        dom.exigir_pendiente(r, "solo se paga una reserva pendiente")
        saga_id = str(uuid.uuid4())
        estado = dom.nuevo_estado(saga_id, p, tipo="pagar", compensable=False, reservaId=p["reserva_id"])
        self._almacen.guardar_saga(saga_id, estado)
        pago = self._pagos.cobrar(dom.datos_cobro(p["reserva_id"], p, saga_id))
        estado.update(step=1, pagoId=pago["pagoId"], ticketId=pago["ticketId"])
        if pago.get("stripe"):
            estado["status"] = PENDING_PAYMENT
            self._almacen.guardar_saga(saga_id, estado)
            out = dom.respuesta(saga_id, PENDING_PAYMENT, p["reserva_id"], pago, qr=None, stripe=pago["stripe"])
            self._almacen.guardar_respuesta_idempotencia(p["idempotency_key"], out)
            return out
        try:
            confirmada, conf = self._reservas.confirmar_reserva(p["reserva_id"])
            if not confirmada:
                raise RuntimeError("No se pudo confirmar la reserva")
        except Exception as e:                       # compensación: el cobro se devuelve y la reserva sigue pendiente
            try:
                self._pagos.devolver_pago(pago["pagoId"])
            except Exception:
                pass
            estado.update(status=COMPENSATED, error=str(e), finished_at=dom.ahora_iso())
            self._almacen.guardar_saga(saga_id, estado)
            raise
        estado.update(step=2, status=COMPLETED, qr=conf.get("qr"), finished_at=dom.ahora_iso())
        self._almacen.guardar_saga(saga_id, estado)
        out = dom.respuesta(saga_id, COMPLETED, p["reserva_id"], pago, qr=conf.get("qr"), stripe=None)
        self._almacen.guardar_respuesta_idempotencia(p["idempotency_key"], out)
        return out

    def cancelar_sin_pago(self, reserva_id: str) -> dict:
        """Cancela una reserva que aún no se pagó y devuelve su porción al cupo (no hay pago que devolver)."""
        r = self._reservas.obtener_reserva(reserva_id)
        dom.exigir_pendiente(r, "solo se cancela sin devolución una reserva pendiente de pago")
        self._reservas.cancelar_reserva(reserva_id)             # primero la reserva (la que manda); luego el cupo
        self._menu.liberar_porcion(r["menuId"], r["platoId"])
        return {"status": COMPLETED, "reservaId": reserva_id}

    def confirmar_pago(self, reserva_id: str, referencia: str) -> dict:
        """Verifica el pago contra Stripe y, solo si está pagado, confirma la reserva y emite el QR."""
        info = self._pagos.verificar_pago(referencia)
        if not info.get("paid"):
            return {"confirmada": False, "status": info.get("status", "pendiente")}
        confirmada, conf = self._reservas.confirmar_reserva(reserva_id)
        if not confirmada:
            # ya confirmada antes (reintento): no es error para el usuario
            return {"confirmada": True, "reservaId": reserva_id, "qr": None, "yaConfirmada": True}
        return {"confirmada": True, "reservaId": reserva_id, "qr": conf.get("qr")}

    def cancelar(self, p: dict) -> dict:
        """Saga 2: devolver pago -> liberar porción -> cancelar reserva."""
        saga_id = str(uuid.uuid4())
        estado = dom.nuevo_estado(saga_id, p, compensable=False)
        self._almacen.guardar_saga(saga_id, estado)
        if p.get("saga_id") and not (p.get("menu_id") and p.get("plato_id")):
            origen = (self._almacen.obtener_saga(p["saga_id"]) or {}).get("payload", {})
            p["menu_id"] = p.get("menu_id") or origen.get("menu_id")
            p["plato_id"] = p.get("plato_id") or origen.get("plato_id")
        self._pagos.devolver_pago(p["pago_id"])
        estado["step"] = 1; self._almacen.guardar_saga(saga_id, estado)
        # Liberar porción: necesitamos menuId/platoId del evento; en MVP se pasa en payload si se tiene
        if p.get("menu_id") and p.get("plato_id"):
            self._menu.liberar_porcion(p["menu_id"], p["plato_id"])
        estado["step"] = 2; self._almacen.guardar_saga(saga_id, estado)
        self._reservas.cancelar_reserva(p["reserva_id"])
        estado.update(step=3, status=COMPLETED, finished_at=dom.ahora_iso())
        self._almacen.guardar_saga(saga_id, estado)
        return {"sagaId": saga_id, "status": COMPLETED}

    def get_estado(self, saga_id: str) -> dict | None:
        return self._almacen.obtener_saga(saga_id)

    def _compensar(self, estado: dict):
        for comp in dom.compensaciones_en_orden(estado):
            try:
                if comp["srv"] == "pagos":
                    self._pagos.devolver_pago(comp["pagoId"])
                elif comp["srv"] == "menu":
                    self._menu.liberar_porcion(comp["menuId"], comp["platoId"])
                elif comp["srv"] == "comensales":
                    self._reservas.cancelar_reserva(comp["reservaId"])
            except Exception:
                pass  # Compensación best-effort; errores quedan en logs
