"""Convierte lo que calculan los agentes en propuestas para el administrador (panel + Telegram)."""
import hashlib
from datetime import date

from app.services import propuestas, push, telegram_bot

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
TURNO = {"DESAYUNO": "Desayuno", "ALMUERZO": "Almuerzo", "CENA": "Cena"}


ROLES_ADMIN = ["administrador"]


def _push(roles: list[str], titulo: str, cuerpo: str, datos: dict) -> None:
    """Aviso al celular. Es «lo mejor posible»: nunca detiene al agente (Telegram y el panel siguen avisando)."""
    try:
        push.enviar_a_roles(roles, titulo, cuerpo, datos)
    except Exception:
        pass


def _publicar(p: dict, nueva: bool, texto: str) -> dict:
    if nueva:
        telegram_bot.encolar(texto, p["id"])
    return {"id": p["id"], "estado": p["estado"], "nueva": nueva}


def proponer_inventario(r: dict, forzar: bool = False) -> dict | None:
    if not (r.get("requiereAviso") and r.get("ordenesBorrador")):
        if forzar:                                       # el administrador pulsó «Ejecutar»: que sepa que no hay nada que comprar
            _push(ROLES_ADMIN, "Inventario y compras", "Sin alertas: no hay stock bajo ni lotes por vencer que requieran compra.", {"tipo": "inventario"})
        return None
    p, nueva = propuestas.registrar(
        "compra", r["claveAlerta"], f"Orden de compra ({r['severidad']}): {len(r['ordenesBorrador'])} insumos, {r['totalBorradorBs']} Bs",
        r["mensajeAdmin"], r, forzar=forzar)
    if nueva:
        if not _push_inventario(r, p["id"]):           # sin detalle de insumos: igual se avisa al administrador
            _push(ROLES_ADMIN, "Inventario: orden de compra propuesta", f"{len(r['ordenesBorrador'])} insumos, {r['totalBorradorBs']} Bs. Revísala y apruébala.",
                  {"tipo": "propuesta", "propuesta": p["id"]})
    return _publicar(p, nueva, r["mensajeAdmin"])


ROLES_INVENTARIO = ["administrador", "cocina_almacen"]


def _push_inventario(r: dict, propuesta_id: str) -> bool:
    """Stock bajo o lotes por vencer: aviso al celular del administrador y de cocina. Devuelve si había algo que avisar."""
    try:
        bajos = [i["nombre"] for i in r.get("insumosEnRiesgo", [])]
        vencen = [f"{x['nombre']} ({x['diasRestantes']} d)" for x in r.get("lotesPorVencer", [])]
        partes = []
        if bajos:
            partes.append("Stock bajo: " + ", ".join(bajos[:3]) + (f" y {len(bajos) - 3} más" if len(bajos) > 3 else ""))
        if vencen:
            partes.append("Por vencer: " + ", ".join(vencen[:3]) + (f" y {len(vencen) - 3} más" if len(vencen) > 3 else ""))
        if not partes:
            return False
        push.enviar_a_roles(ROLES_INVENTARIO, f"Inventario: alerta {r['severidad']}", ". ".join(partes) + ".",
                            {"tipo": "stock_bajo", "propuesta": propuesta_id})
        return True
    except Exception:
        return False


def _texto_menu(r: dict) -> str:
    dias: dict[str, dict[str, list]] = {}
    for it in r["propuesta"]:
        dias.setdefault(it["fecha"], {}).setdefault(it["turno"], []).append(it["platoId"].replace("plato-", ""))
    lineas = [f"Menú propuesto para la semana del {r['semanaInicio']}:"]
    for f, turnos in sorted(dias.items()):
        d = date.fromisoformat(f)
        partes = " · ".join(f"{TURNO[t]}: {', '.join(pl)}" for t, pl in turnos.items())
        lineas.append(f"{DIAS[d.weekday()]} {d.strftime('%d/%m')} — {partes}")
    sin_nutri = sum(1 for it in r["propuesta"] if not it["cumpleRequisitosNutricionales"] and it["turno"] == "ALMUERZO")
    ahorro = sum(1 for it in r["propuesta"] if it["aprovechaInsumosPorVencer"])
    if ahorro:
        lineas.append(f"{ahorro} platos aprovechan insumos por vencer.")
    if sin_nutri:
        lineas.append(f"Atención: {sin_nutri} almuerzos no llegan al mínimo nutricional.")
    lineas.append("Las raciones salen del modelo predictivo. ¿Publico este menú?")
    return "\n".join(lineas)


def proponer_menu(r: dict, forzar: bool = False) -> dict:
    texto = _texto_menu(r)
    p, nueva = propuestas.registrar("menu", f"menu:{r['semanaInicio']}", f"Menú de la semana del {r['semanaInicio']}",
                                    texto, r, forzar=forzar)
    if nueva:
        _push(ROLES_ADMIN, "Menú propuesto", f"Semana del {r['semanaInicio']}: {len(r['propuesta'])} platos. Revísalo y apruébalo.",
              {"tipo": "propuesta", "propuesta": p["id"]})
    return _publicar(p, nueva, texto)


def avisar_monitor(r: dict, forzar: bool = False) -> dict | None:
    if not r.get("hallazgos"):
        if forzar:                                       # el administrador pulsó «Ejecutar»: que sepa que no hay novedades
            _push(ROLES_ADMIN, "Monitor del comedor", "Sin novedades: no se detectó ningún problema.", {"tipo": "monitor"})
        return None
    lineas = [f"Monitor del comedor — {r['resumenEjecutivo']}"]
    lineas += [f"[{h['severidad']}] {h['mensaje']} → {h['recomendacion']}" for h in r["hallazgos"][:12]]
    texto = "\n".join(lineas)
    clave = "mon:" + hashlib.md5("|".join(h["mensaje"] for h in r["hallazgos"]).encode()).hexdigest()[:10]
    p, nueva = propuestas.registrar("info", clave, "Informe del monitor", texto, {}, forzar=forzar, informativa=True)
    if nueva:
        telegram_bot.encolar(texto)
        n = len(r["hallazgos"])
        _push(ROLES_ADMIN, "Monitor del comedor", f"{n} hallazgo{'s' if n != 1 else ''}: {r['resumenEjecutivo']}"[:300],
              {"tipo": "monitor", "propuesta": p["id"]})
    return {"id": p["id"], "estado": p["estado"], "nueva": nueva}


# ----------------------------- decisiones desde el panel -----------------------------

def avisar_resultado(p: dict) -> None:
    """Cuando se decide desde el panel, Telegram también se entera del resultado."""
    icono = {"EJECUTADA": "✅", "RECHAZADA": "❌", "ERROR": "⚠️"}.get(p["estado"], "ℹ️")
    telegram_bot.encolar(f"{icono} {p['titulo']}" + chr(10) + f"{p['resultado'] or p['estado']}")


def decidir_desde_panel(pid: str, aprobar: bool) -> dict | None:
    """Aprueba o rechaza desde el panel. None si la propuesta no existe."""
    antes = propuestas.obtener(pid)
    p = propuestas.resolver(pid, aprobar, "panel")
    if p is not None and antes and antes["estado"] == "PENDIENTE":
        avisar_resultado(p)
    return p


def sincronizar(items: list[dict]) -> list[dict]:
    """Recibe lo que el navegador generó/decidió sin conexión: lo registra, avisa a Telegram y ejecuta lo aprobado."""
    salida = []
    for it in items:
        if it["tipo"] not in ("menu", "compra", "info"):
            continue
        p, nueva = propuestas.registrar(it["tipo"], it["clave"], it["titulo"], it["resumen"], it["payload"],
                                        informativa=it["tipo"] == "info")
        if nueva:
            telegram_bot.encolar(it["resumen"], None if it["tipo"] == "info" else p["id"])
            _push(ROLES_ADMIN, it["titulo"][:100], "Generado sin conexión y ya sincronizado. Revísalo en el panel.",
                  {"tipo": "propuesta", "propuesta": p["id"]})
        if it.get("decision") and p["estado"] == "PENDIENTE":
            p = propuestas.resolver(p["id"], it["decision"] == "aprobar", "panel (decidido sin conexión)")
            avisar_resultado(p)
        salida.append({"clave": it["clave"], "id": p["id"], "estado": p["estado"]})
    return salida
