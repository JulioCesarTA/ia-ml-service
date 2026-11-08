"""Esquemas de entrada de la API de sagas."""
from pydantic import BaseModel


class ReservarYPagarReq(BaseModel):
    estudiante_id: str
    menu_id: str
    plato_id: str
    fecha: str
    turno: str
    metodo_pago: str  # qr_bancario | efectivo | beca
    monto: float
    idempotency_key: str


class CancelarReq(BaseModel):
    reserva_id: str
    pago_id: str
    idempotency_key: str
    menu_id: str | None = None
    plato_id: str | None = None
    saga_id: str | None = None  # saga de la reserva: de ahí se deducen menu_id y plato_id si faltan


class ConfirmarPagoReq(BaseModel):
    reserva_id: str
    referencia: str
