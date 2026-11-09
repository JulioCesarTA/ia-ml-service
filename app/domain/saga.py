"""Modelo de las sagas (SPEC §5): estado guardado, pasos, compensaciones y respuestas.

Saga 1: reservar + apartar porción + cobrar + confirmar.
Saga 2: cancelar (devolver pago -> liberar porción -> cancelar reserva).
La forma de estos diccionarios es la que se guarda en DynamoDB: no debe cambiar.
"""
from datetime import datetime

RUNNING, PENDING_PAYMENT, COMPLETED, COMPENSATED, RESERVED = "RUNNING", "PENDING_PAYMENT", "COMPLETED", "COMPENSATED", "RESERVED"
METODOS_PAGO_DIFERIDO = ("qr_bancario", "efectivo")


def ahora_iso() -> str:
    return datetime.utcnow().isoformat()


def nuevo_estado(saga_id: str, payload: dict, tipo: str | None = None, compensable: bool = True, **extra) -> dict:
    """Estado inicial de una saga (paso 0, RUNNING)."""
    estado = {"sagaId": saga_id}
    if tipo:
        estado["tipo"] = tipo
    estado.update(step=0, status=RUNNING, payload=payload)
    estado.update(extra)
    if compensable:
        estado["compensations"] = []
    estado["started_at"] = ahora_iso()
    return estado


def datos_reserva(p: dict, saga_id: str) -> dict:
    return {"estudianteId": p["estudiante_id"], "menuId": p["menu_id"], "platoId": p["plato_id"],
            "fecha": p["fecha"], "turno": p["turno"], "sagaId": saga_id}


def datos_cobro(reserva_id: str, p: dict, saga_id: str) -> dict:
    return {"reservaId": reserva_id, "estudianteId": p["estudiante_id"], "monto": p["monto"],
            "metodo": p["metodo_pago"], "sagaId": saga_id}


def comp_cancelar_reserva(reserva_id: str) -> dict:
    return {"srv": "comensales", "accion": "cancelar", "reservaId": reserva_id}


def comp_liberar_porcion(menu_id: str, plato_id: str) -> dict:
    return {"srv": "menu", "accion": "liberar", "menuId": menu_id, "platoId": plato_id}


def comp_devolver_pago(pago_id: str) -> dict:
    return {"srv": "pagos", "accion": "devolver", "pagoId": pago_id}


def compensaciones_en_orden(estado: dict) -> list[dict]:
    """Las compensaciones se ejecutan en orden inverso al de los pasos."""
    return list(reversed(estado.get("compensations", [])))


def respuesta(saga_id: str, status: str, reserva_id: str, pago: dict | None = None, qr=None, stripe=None, **extra) -> dict:
    out = {"sagaId": saga_id, "status": status, "reservaId": reserva_id}
    if pago is not None:
        out.update(pagoId=pago["pagoId"], ticketId=pago["ticketId"])
    out.update(extra)
    out.update(qr=qr, stripe=stripe)
    return out


def es_reutilizable(cached: dict | None) -> bool:
    """Una respuesta de idempotencia guardada solo se devuelve si la saga llegó a crearse."""
    return bool(cached and cached.get("sagaId"))


def beca_cubre(beca: dict) -> bool:
    return bool(beca.get("tieneBeca") and beca.get("cubreHoy"))


def validar_metodo_pago_diferido(metodo: str) -> None:
    if metodo not in METODOS_PAGO_DIFERIDO:
        raise ValueError("metodo_pago debe ser qr_bancario o efectivo")


def exigir_pendiente(reserva: dict, motivo: str) -> None:
    if reserva["estado"] != "pendiente":
        raise ValueError(f"La reserva está «{reserva['estado']}»: {motivo}")
