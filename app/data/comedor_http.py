"""Clientes HTTP de los demás microservicios del comedor: menú e inventario, comensales y reservas, pagos."""
import os

import httpx

_SERVICIOS = {
    "menu": ("MENU_URL", "http://menu-inventario-service:8080"),
    "comensales": ("COMENSALES_URL", "http://comensales-reservas-service:8080"),
    "pagos": ("PAGOS_URL", "http://pagos-tickets-service:8080"),
}


def url(servicio: str) -> str:
    var, defecto = _SERVICIOS[servicio]
    return os.getenv(var, defecto)


def leer_json(direccion: str, espera: float = 20):
    """GET que devuelve el JSON; lanza excepción si el servicio no responde o contesta con error."""
    r = httpx.get(direccion, timeout=espera)
    r.raise_for_status()
    return r.json()


# ----------------------------- menú e inventario -----------------------------

def menus_semana(turno: str, inicio: str | None = None) -> list[dict]:
    r = httpx.get(f"{url('menu')}/menus/semana/{turno}", params={"inicio": inicio} if inicio else None, timeout=10)
    return r.json() if r.status_code == 200 else []


def menus_historial(desde: str, hasta: str) -> list[dict]:
    """Todos los menús (todos los turnos) entre dos fechas, en una sola llamada. Lanza excepción si el servicio no lo ofrece."""
    r = httpx.get(f"{url('menu')}/menus/historial", params={"desde": desde, "hasta": hasta}, timeout=60)
    r.raise_for_status()
    return r.json()


def apartar_porcion(menu_id: str, plato_id: str) -> None:
    httpx.post(f"{url('menu')}/porciones/apartar", json={"menuId": menu_id, "platoId": plato_id}, timeout=10).raise_for_status()


def liberar_porcion(menu_id: str, plato_id: str) -> None:
    httpx.post(f"{url('menu')}/porciones/liberar", json={"menuId": menu_id, "platoId": plato_id}, timeout=10)


# ----------------------------- comensales y reservas -----------------------------

def estudiantes() -> list[dict]:
    return httpx.get(f"{url('comensales')}/estudiantes", timeout=10).json()


def beca(username: str) -> dict:
    try:
        return httpx.get(f"{url('comensales')}/estudiantes/{username}/beca", timeout=10).json() or {}
    except Exception:
        return {}


def obtener_reserva(reserva_id: str) -> dict:
    """La reserva tal como está en comensales: {id, estudianteId, menuId, platoId, fecha, turno, estado, qr}."""
    r = httpx.get(f"{url('comensales')}/reservas/{reserva_id}", timeout=10)
    if r.status_code == 404:
        raise ValueError("La reserva no existe")
    r.raise_for_status()
    return r.json()


def crear_reserva(datos: dict) -> str:
    """Crea la reserva pendiente y devuelve su id. Una segunda reserva el mismo día lanza ValueError con el motivo."""
    r = httpx.post(f"{url('comensales')}/reservas", json=datos, timeout=10)
    if r.status_code == 409:
        raise ValueError(r.json().get("message", "Reserva duplicada"))
    r.raise_for_status()
    return r.json()["id"]


def confirmar_reserva(reserva_id: str) -> tuple[bool, dict]:
    """(se_confirmó, respuesta). `False` también cuando ya estaba confirmada."""
    r = httpx.post(f"{url('comensales')}/reservas/{reserva_id}/confirmar", timeout=15)
    return r.status_code < 400, (r.json() if r.status_code < 400 else {})


def cancelar_reserva(reserva_id: str) -> None:
    httpx.post(f"{url('comensales')}/reservas/{reserva_id}/cancelar", timeout=10).raise_for_status()


# ----------------------------- pagos -----------------------------

def cobrar(datos: dict) -> dict:
    r = httpx.post(f"{url('pagos')}/pagos/cobrar", json=datos, timeout=10)
    r.raise_for_status()
    return r.json()


def verificar_pago(referencia: str) -> dict:
    r = httpx.get(f"{url('pagos')}/pagos/verificar/{referencia}", timeout=15)
    r.raise_for_status()
    return r.json()


def devolver_pago(pago_id: str) -> None:
    httpx.post(f"{url('pagos')}/pagos/{pago_id}/devolver", timeout=10).raise_for_status()


def recibo(referencia: str) -> dict:
    return httpx.get(f"{url('pagos')}/pagos/recibo/{referencia}", timeout=20).json()
