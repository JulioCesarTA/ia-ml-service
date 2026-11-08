"""Saga Orchestrator — SPEC §5. Estado en DynamoDB.
Saga 1: reservar + apartar porción + cobrar + confirmar.
Saga 2: cancelar (devolver pago -> liberar porción -> cancelar reserva)."""
import uuid
from datetime import datetime

from app.data import comedor_http as srv, dynamo_client


class SagaOrchestrator:

    def __init__(self):
        try: dynamo_client.ensure_tables()
        except Exception: pass

    def reservar_y_pagar(self, p: dict) -> dict:
        # Idempotencia
        cached = dynamo_client.check_and_lock_idempotency(p["idempotency_key"])
        if cached and cached.get("sagaId"): return cached

        saga_id = str(uuid.uuid4())
        estado = {"sagaId": saga_id, "step": 0, "status": "RUNNING", "payload": p,
                  "compensations": [], "started_at": datetime.utcnow().isoformat()}
        dynamo_client.put_saga(saga_id, estado)

        try:
            # Paso 1: crear reserva pendiente
            reserva_id = srv.crear_reserva({
                "estudianteId": p["estudiante_id"], "menuId": p["menu_id"],
                "platoId": p["plato_id"], "fecha": p["fecha"], "turno": p["turno"],
                "sagaId": saga_id,
            })
            estado.update(step=1, reservaId=reserva_id)
            estado["compensations"].append({"srv": "comensales", "accion": "cancelar", "reservaId": reserva_id})
            dynamo_client.put_saga(saga_id, estado)

            # Paso 2: apartar porción
            srv.apartar_porcion(p["menu_id"], p["plato_id"])
            estado["step"] = 2
            estado["compensations"].append({"srv": "menu", "accion": "liberar",
                                             "menuId": p["menu_id"], "platoId": p["plato_id"]})
            dynamo_client.put_saga(saga_id, estado)

            # Paso 3: cobrar
            pago = srv.cobrar({
                "reservaId": reserva_id, "estudianteId": p["estudiante_id"],
                "monto": p["monto"], "metodo": p["metodo_pago"], "sagaId": saga_id,
            })
            estado.update(step=3, pagoId=pago["pagoId"], ticketId=pago["ticketId"])
            estado["compensations"].append({"srv": "pagos", "accion": "devolver", "pagoId": pago["pagoId"]})
            dynamo_client.put_saga(saga_id, estado)

            # Pago con QR/tarjeta: la reserva queda pendiente hasta que el pago se verifique.
            if pago.get("stripe"):
                estado.update(step=3, status="PENDING_PAYMENT")
                dynamo_client.put_saga(saga_id, estado)
                out = {"sagaId": saga_id, "status": "PENDING_PAYMENT",
                       "reservaId": reserva_id, "pagoId": pago["pagoId"],
                       "ticketId": pago["ticketId"], "qr": None,
                       "stripe": pago.get("stripe")}
                dynamo_client.save_idempotency_response(p["idempotency_key"], out)
                return out

            # Paso 4: confirmar reserva + emitir QR (beca / efectivo)
            confirmada, conf = srv.confirmar_reserva(reserva_id)
            if not confirmada:
                raise RuntimeError("No se pudo confirmar la reserva")
            estado.update(step=4, status="COMPLETED", qr=conf.get("qr"),
                          finished_at=datetime.utcnow().isoformat())
            dynamo_client.put_saga(saga_id, estado)

            out = {"sagaId": saga_id, "status": "COMPLETED",
                   "reservaId": reserva_id, "pagoId": pago["pagoId"],
                   "ticketId": pago["ticketId"], "qr": conf.get("qr"),
                   "stripe": None}
            dynamo_client.save_idempotency_response(p["idempotency_key"], out)
            return out

        except Exception as e:
            # Compensar en orden inverso
            self._compensar(estado)
            estado.update(status="COMPENSATED", error=str(e),
                          finished_at=datetime.utcnow().isoformat())
            dynamo_client.put_saga(saga_id, estado)
            raise

    def confirmar_pago(self, reserva_id: str, referencia: str) -> dict:
        """Verifica el pago contra Stripe y, solo si está pagado, confirma la reserva y emite el QR."""
        info = srv.verificar_pago(referencia)
        if not info.get("paid"):
            return {"confirmada": False, "status": info.get("status", "pendiente")}
        confirmada, conf = srv.confirmar_reserva(reserva_id)
        if not confirmada:
            # ya confirmada antes (reintento): no es error para el usuario
            return {"confirmada": True, "reservaId": reserva_id, "qr": None, "yaConfirmada": True}
        return {"confirmada": True, "reservaId": reserva_id, "qr": conf.get("qr")}

    def cancelar(self, p: dict) -> dict:
        """Saga 2: devolver pago -> liberar porción -> cancelar reserva."""
        saga_id = str(uuid.uuid4())
        estado = {"sagaId": saga_id, "step": 0, "status": "RUNNING",
                  "payload": p, "started_at": datetime.utcnow().isoformat()}
        dynamo_client.put_saga(saga_id, estado)
        if p.get("saga_id") and not (p.get("menu_id") and p.get("plato_id")):
            origen = (dynamo_client.get_saga(p["saga_id"]) or {}).get("payload", {})
            p["menu_id"] = p.get("menu_id") or origen.get("menu_id")
            p["plato_id"] = p.get("plato_id") or origen.get("plato_id")
        srv.devolver_pago(p["pago_id"])
        estado["step"] = 1; dynamo_client.put_saga(saga_id, estado)
        # Liberar porción: necesitamos menuId/platoId del evento; en MVP se pasa en payload si se tiene
        if p.get("menu_id") and p.get("plato_id"):
            srv.liberar_porcion(p["menu_id"], p["plato_id"])
        estado["step"] = 2; dynamo_client.put_saga(saga_id, estado)
        srv.cancelar_reserva(p["reserva_id"])
        estado.update(step=3, status="COMPLETED",
                      finished_at=datetime.utcnow().isoformat())
        dynamo_client.put_saga(saga_id, estado)
        return {"sagaId": saga_id, "status": "COMPLETED"}

    def get_estado(self, saga_id: str) -> dict | None:
        return dynamo_client.get_saga(saga_id)

    def _compensar(self, estado: dict):
        for comp in reversed(estado.get("compensations", [])):
            try:
                if comp["srv"] == "pagos":
                    srv.devolver_pago(comp["pagoId"])
                elif comp["srv"] == "menu":
                    srv.liberar_porcion(comp["menuId"], comp["platoId"])
                elif comp["srv"] == "comensales":
                    srv.cancelar_reserva(comp["reservaId"])
            except Exception:
                pass  # Compensación best-effort; errores quedan en logs
