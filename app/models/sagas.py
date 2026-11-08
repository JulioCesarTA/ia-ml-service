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


class ConfirmarPagoReq(BaseModel):
    reserva_id: str
    referencia: str
