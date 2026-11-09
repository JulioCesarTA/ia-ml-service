"""Reglas de las propuestas que los agentes someten al administrador: estados y qué hace cada una al aprobarse."""
from collections import defaultdict

PENDIENTE, EJECUTANDO, EJECUTADA, RECHAZADA, ERROR, INFORMATIVA = (
    "PENDIENTE", "EJECUTANDO", "EJECUTADA", "RECHAZADA", "ERROR", "INFORMATIVA")
VENTANA_S_DEFECTO = 12 * 3600       # no repetir la misma alerta dentro de esta ventana
ICONO_RESULTADO = {EJECUTADA: "✅", RECHAZADA: "❌", ERROR: "⚠️"}


def texto_resultado(p: dict) -> str:
    """Aviso del resultado de una decisión (para Telegram)."""
    icono = ICONO_RESULTADO.get(p["estado"], "ℹ️")
    return f"{icono} {p['titulo']}" + chr(10) + f"{p['resultado'] or p['estado']}"


# ----------------------------- menú -----------------------------

def menus_a_publicar(payload: dict) -> dict[tuple[str, str], list]:
    """{(fecha, turno): [{platoId, cupo}]} con al menos 1 ración por plato."""
    grupos: dict[tuple[str, str], list] = defaultdict(list)
    for it in payload.get("propuesta", []):
        grupos[(it["fecha"], it["turno"])].append({"platoId": it["platoId"], "cupo": max(1, int(it["racionesSugeridas"]))})
    return grupos


def resultado_publicacion(publicados: int, omitidos: int, fallidos: int) -> tuple[str, bool]:
    txt = f"Menús publicados: {publicados}"
    if omitidos:
        txt += f"; omitidos {omitidos} que ya existían"
    if fallidos:
        txt += f"; {fallidos} fallaron"
    return txt, fallidos == 0 and publicados + omitidos > 0


# ----------------------------- compra -----------------------------

def por_proveedor(ordenes: list[dict]) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for o in ordenes:
        out[o.get("proveedorSugerido", "A definir")].append(o)
    return out


def cuerpo_orden_aprobada(pid: str, grupos: dict[str, list]) -> dict:
    """Lo que n8n recibe para registrar la obligación de pago por proveedor (SPEC §9, flujo 2)."""
    return {"ordenId": pid, "proveedores": [
        {"proveedor": prov, "monto": round(sum(i["subtotalBs"] for i in items), 2),
         "detalle": [f"{i['nombre']}: {i['cantidadSugerida']} {i['unidad']}" for i in items]}
        for prov, items in grupos.items()]}


def texto_orden_aprobada(payload: dict, grupos: dict[str, list]) -> str:
    lineas = ["Orden de compra APROBADA. Pedir a cada proveedor:"]
    for prov, items in grupos.items():
        sub = sum(i["subtotalBs"] for i in items)
        lineas.append(f"\n{prov} ({round(sub, 2)} Bs)")
        lineas += [f"  - {i['nombre']}: {i['cantidadSugerida']} {i['unidad']}" for i in items]
    lineas.append(f"\nTotal: {payload.get('totalBorradorBs', 0)} Bs")
    return "\n".join(lineas)
