"""Textos y destinatarios de los avisos que generan los agentes (panel, Telegram y push)."""
import hashlib
from datetime import date

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
TURNO = {"DESAYUNO": "Desayuno", "ALMUERZO": "Almuerzo", "CENA": "Cena"}
ROLES_ADMIN = ["administrador"]
ROLES_INVENTARIO = ["administrador", "cocina_almacen"]
TIPOS_SINCRONIZABLES = ("menu", "compra", "info")


def partes_inventario(r: dict) -> list[str]:
    """Stock bajo y lotes por vencer en una o dos frases (vacío si no hay nada que avisar)."""
    bajos = [i["nombre"] for i in r.get("insumosEnRiesgo", [])]
    vencen = [f"{x['nombre']} ({x['diasRestantes']} d)" for x in r.get("lotesPorVencer", [])]
    partes = []
    if bajos:
        partes.append("Stock bajo: " + ", ".join(bajos[:3]) + (f" y {len(bajos) - 3} más" if len(bajos) > 3 else ""))
    if vencen:
        partes.append("Por vencer: " + ", ".join(vencen[:3]) + (f" y {len(vencen) - 3} más" if len(vencen) > 3 else ""))
    return partes


def texto_menu(r: dict) -> str:
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


def texto_monitor(r: dict) -> str:
    lineas = [f"Monitor del comedor — {r['resumenEjecutivo']}"]
    lineas += [f"[{h['severidad']}] {h['mensaje']} → {h['recomendacion']}" for h in r["hallazgos"][:12]]
    return "\n".join(lineas)


def clave_monitor(r: dict) -> str:
    """Los mismos hallazgos dan la misma clave: así el informe no se repite."""
    return "mon:" + hashlib.md5("|".join(h["mensaje"] for h in r["hallazgos"]).encode()).hexdigest()[:10]
