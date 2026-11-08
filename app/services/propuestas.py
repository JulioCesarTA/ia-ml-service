"""Propuestas de los agentes que requieren aprobación del administrador.

Todo se guarda en SQLite local (sin internet): propuestas, cola de mensajes a Telegram
y configuración. Al aprobar una propuesta se ejecuta su acción:
  - menu:   publica los menús propuestos en menu-inventario-service.
  - compra: deja la orden de compra aprobada y lista para enviar a los proveedores.
"""
import os
from collections import defaultdict

from app.data import comedor_http, repo_propuestas

VENTANA_S = int(os.getenv("AVISO_VENTANA_S", str(12 * 3600)))


def obtener(pid: str) -> dict | None:
    return repo_propuestas.obtener(pid)


def listar(estado: str | None = None, limite: int = 30) -> list[dict]:
    return repo_propuestas.listar(estado, limite)


def registrar(tipo: str, clave: str, titulo: str, resumen: str, payload: dict,
              forzar: bool = False, informativa: bool = False) -> tuple[dict, bool]:
    """Crea la propuesta. Devuelve (propuesta, es_nueva). No repite la misma alerta dentro de la ventana."""
    return repo_propuestas.crear_si_no_hay_vigente(tipo, clave, titulo, resumen, payload, forzar, informativa, VENTANA_S)


def resolver(pid: str, aprobar: bool, canal: str = "panel") -> dict | None:
    """Aprueba (y ejecuta) o rechaza. Solo actúa si sigue PENDIENTE; si no, devuelve el estado actual."""
    if not repo_propuestas.tomar_pendiente(pid, "EJECUTANDO" if aprobar else "RECHAZADA",
                                           None if aprobar else f"Rechazada desde {canal}"):
        return obtener(pid)
    p = obtener(pid)
    if p is None or not aprobar:
        return p
    try:
        ejecutor = {"menu": _ejecutar_menu, "compra": _ejecutar_compra}[p["tipo"]]
        resultado, ok = ejecutor(p["payload"])
    except Exception as e:  # el administrador ve el error y puede reintentar con una propuesta nueva
        resultado, ok = f"No se pudo ejecutar: {e}", False
    repo_propuestas.cerrar(pid, "EJECUTADA" if ok else "ERROR", f"{resultado} (aprobada desde {canal})")
    return obtener(pid)


# ----------------------------- ejecutores -----------------------------

def _ejecutar_menu(payload: dict) -> tuple[str, bool]:
    grupos: dict[tuple[str, str], list] = defaultdict(list)
    for it in payload.get("propuesta", []):
        grupos[(it["fecha"], it["turno"])].append({"platoId": it["platoId"], "cupo": max(1, int(it["racionesSugeridas"]))})
    publicados = omitidos = fallidos = 0
    existentes: dict[str, set] = {}
    for turno in {t for _, t in grupos}:
        try:
            existentes[turno] = {m.get("fecha") for m in comedor_http.menus_semana(turno)}
        except Exception:
            existentes[turno] = set()
    for (fecha, turno), platos in sorted(grupos.items()):
        if fecha in existentes.get(turno, set()):
            omitidos += 1
            continue
        if comedor_http.publicar_menu(fecha, turno, platos):
            publicados += 1
        else:
            fallidos += 1
    txt = f"Menús publicados: {publicados}"
    if omitidos:
        txt += f"; omitidos {omitidos} que ya existían"
    if fallidos:
        txt += f"; {fallidos} fallaron"
    return txt, fallidos == 0 and publicados + omitidos > 0


def _ejecutar_compra(payload: dict) -> tuple[str, bool]:
    ordenes = payload.get("ordenesBorrador", [])
    if not ordenes:
        return "No había líneas de compra", False
    from app.services import telegram_bot  # import tardío: telegram_bot usa este módulo
    por_proveedor: dict[str, list] = defaultdict(list)
    for o in ordenes:
        por_proveedor[o.get("proveedorSugerido", "A definir")].append(o)
    lineas = ["Orden de compra APROBADA. Pedir a cada proveedor:"]
    for prov, items in por_proveedor.items():
        sub = sum(i["subtotalBs"] for i in items)
        lineas.append(f"\n{prov} ({round(sub, 2)} Bs)")
        lineas += [f"  - {i['nombre']}: {i['cantidadSugerida']} {i['unidad']}" for i in items]
    lineas.append(f"\nTotal: {payload.get('totalBorradorBs', 0)} Bs")
    telegram_bot.encolar("\n".join(lineas))
    return f"Orden aprobada: {len(ordenes)} insumos, {payload.get('totalBorradorBs', 0)} Bs", True
