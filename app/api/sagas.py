"""SPEC §5: Saga orchestrator + idempotencia (estado en DynamoDB)."""
from fastapi import APIRouter, HTTPException
from app.models.sagas import CancelarReq, ConfirmarPagoReq, ReservarYPagarReq
from app.services.saga.orchestrator import SagaOrchestrator

router = APIRouter()


@router.post("/reservar-y-pagar")
def saga1(body: ReservarYPagarReq):
    try:
        return SagaOrchestrator().reservar_y_pagar(body.model_dump())
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/cancelar")
def saga2(body: CancelarReq):
    try:
        return SagaOrchestrator().cancelar(body.model_dump())
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/confirmar-pago")
def confirmar_pago(body: ConfirmarPagoReq):
    try:
        return SagaOrchestrator().confirmar_pago(body.reserva_id, body.referencia)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/{saga_id}")
def estado_saga(saga_id: str):
    return SagaOrchestrator().get_estado(saga_id)
