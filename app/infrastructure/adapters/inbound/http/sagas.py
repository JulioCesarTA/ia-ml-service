"""SPEC §5: Saga orchestrator + idempotencia (estado en DynamoDB)."""
from typing import Callable

from fastapi import APIRouter, HTTPException

from app.application.saga.orquestador import SagaOrchestrator
from app.infrastructure.adapters.inbound.http.esquemas.sagas import (
    CancelarReq, CancelarReservaReq, ConfirmarPagoReq, PagarReq, ReservarReq, ReservarYPagarReq)


def crear_router(nueva_saga: Callable[[], SagaOrchestrator]) -> APIRouter:
    """`nueva_saga` arma un orquestador por petición (como antes: cada uno comprueba que existan las tablas)."""
    router = APIRouter()

    @router.post("/reservar-y-pagar")
    def saga1(body: ReservarYPagarReq):
        try:
            return nueva_saga().reservar_y_pagar(body.model_dump())
        except Exception as e:
            raise HTTPException(400, str(e))

    @router.post("/reservar")
    def reservar(body: ReservarReq):
        try:
            return nueva_saga().reservar(body.model_dump())
        except Exception as e:
            raise HTTPException(400, str(e))

    @router.post("/pagar")
    def pagar(body: PagarReq):
        try:
            return nueva_saga().pagar(body.model_dump())
        except Exception as e:
            raise HTTPException(400, str(e))

    @router.post("/cancelar-reserva")
    def cancelar_reserva(body: CancelarReservaReq):
        try:
            return nueva_saga().cancelar_sin_pago(body.reserva_id)
        except Exception as e:
            raise HTTPException(400, str(e))

    @router.post("/cancelar")
    def saga2(body: CancelarReq):
        try:
            return nueva_saga().cancelar(body.model_dump())
        except Exception as e:
            raise HTTPException(400, str(e))

    @router.post("/confirmar-pago")
    def confirmar_pago(body: ConfirmarPagoReq):
        try:
            return nueva_saga().confirmar_pago(body.reserva_id, body.referencia)
        except Exception as e:
            raise HTTPException(400, str(e))

    @router.get("/{saga_id}")
    def estado_saga(saga_id: str):
        return nueva_saga().get_estado(saga_id)

    return router
