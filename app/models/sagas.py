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


class ReservarReq(BaseModel):
    """Reservar SIN pagar: se paga después desde «Mis reservas» (con beca que cubre, queda todo resuelto)."""
    estudiante_id: str
    menu_id: str
    plato_id: str
    fecha: str
    turno: str
    idempotency_key: str


class PagarReq(BaseModel):
    reserva_id: str
    estudiante_id: str
    metodo_pago: str  # qr_bancario | efectivo
    monto: float
    idempotency_key: str


class CancelarReservaReq(BaseModel):
    """Cancelar una reserva que todavía no se pagó (no hay nada que devolver)."""
    reserva_id: str


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
