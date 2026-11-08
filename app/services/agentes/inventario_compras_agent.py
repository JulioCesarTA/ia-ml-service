"""Agente: Inventario y compras.

Misión: 'Que nunca falte un insumo ni se venza nada.'
  1) Lee insumos y lotes (MCP).
  2) Detecta stock bajo (stock actual <= mínimo) y lotes que vencen en 7 días o menos.
  3) Prepara órdenes de compra en BORRADOR (nunca compra solo).
  4) Si hay algo que decidir, arma el aviso para el administrador.

La versión del navegador (backoffice) implementa exactamente la misma lógica y
produce el mismo texto y la misma clave de alerta, para no avisar dos veces.
"""
import math
from datetime import date

from app.data.mcp_tools import McpToolClient

DIAS_VENCIMIENTO = 7

PROVEEDOR = {
    "ARROZ": "Mayorista Mercado Abasto", "POLLO": "Avicola San Juan", "RES": "Carnes del Oriente",
    "PAPA": "Agro Yungas", "TOMATE": "Mercado Mutualista", "ACEITE": "Industria IOL",
    "SAL": "Salinas Uyuni", "LECHE": "PIL Bolivia", "AZUCAR": "Unagro",
    "CEBOLLA": "Mercado Mutualista", "ZANAH": "Agro Yungas",
}
PRECIO_BS = {
    "ARROZ": 7.5, "POLLO": 25.0, "RES": 55.0, "PAPA": 5.5, "TOMATE": 8.0, "ACEITE": 18.0,
    "SAL": 2.0, "LECHE": 7.0, "AZUCAR": 6.5, "CEBOLLA": 4.5, "ZANAH": 5.0,
}


def _stock(ins: dict) -> float:
    return sum(((l.get("cantidad") or {}).get("valor") or 0) for l in (ins.get("lotes") or []))


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}"


class InventarioComprasAgent:
    def run(self, objetivo: str, contexto: dict) -> dict:
        tools = McpToolClient()
        insumos = tools.ver_stock_insumo() or []
        por_vencer = tools.lotes_por_vencer(dias=DIAS_VENCIMIENTO)

        en_riesgo, ordenes, total_bs = [], [], 0.0
        for ins in insumos:
            actual = _stock(ins)
            minimo = float(ins.get("stockMinimo") or 0)
            if actual > minimo:
                continue
            nombre = str(ins.get("nombre", "")).upper()
            cantidad = max(1, math.ceil(2 * minimo - actual))
            precio = PRECIO_BS.get(nombre, 10.0)
            subtotal = cantidad * precio
            total_bs += subtotal
            en_riesgo.append({"id": ins.get("id"), "nombre": nombre, "stockActual": actual,
                              "stockMinimo": minimo, "unidad": ins.get("unidad")})
            ordenes.append({
                "insumoId": ins.get("id"), "nombre": nombre, "cantidadSugerida": cantidad,
                "unidad": ins.get("unidad"), "precioUnitarioBs": precio,
                "subtotalBs": round(subtotal, 2),
                "proveedorSugerido": PROVEEDOR.get(nombre, "A definir"), "estado": "BORRADOR",
            })

        criticos = sum(1 for l in por_vencer if l["diasRestantes"] <= 2)
        escalar = len(en_riesgo) >= 3 or criticos >= 1 or total_bs > 1500
        requiere_aviso = bool(en_riesgo or por_vencer)
        severidad = "ALTA" if escalar else ("MEDIA" if requiere_aviso else "BAJA")

        lineas = [f"Inventario: alerta {severidad}."]
        if en_riesgo:
            lineas.append("Stock bajo: " + "; ".join(
                f"{i['nombre']} ({_fmt(i['stockActual'])} {i['unidad']}, mínimo {_fmt(i['stockMinimo'])})" for i in en_riesgo) + ".")
        if por_vencer:
            lineas.append("Por vencer: " + "; ".join(
                f"{l['nombre']} {_fmt(l['cantidad'] or 0)} {l['unidad']} vence {l['vence']} ({l['diasRestantes']} días)" for l in por_vencer) + ".")
        if ordenes:
            lineas.append("Orden de compra sugerida (borrador): " + "; ".join(
                f"{o['nombre']} {o['cantidadSugerida']} {o['unidad']}" for o in ordenes) + f". Total {round(total_bs, 2)} Bs.")
        lineas.append("¿Apruebas esta orden de compra?")

        clave = ("ins:" + ",".join(sorted(str(i["id"]) for i in en_riesgo)) +
                 ";lotes:" + ",".join(sorted(f"{l['insumoId']}@{l['vence']}" for l in por_vencer)))

        return {
            "agente": "inventario-compras", "objetivo": objetivo, "fecha": date.today().isoformat(),
            "origenDatos": "servidor", "severidad": severidad,
            "insumosEnRiesgo": en_riesgo, "lotesPorVencer": por_vencer,
            "ordenesBorrador": ordenes, "totalBorradorBs": round(total_bs, 2),
            "escalarAlAdministrador": escalar, "requiereAviso": requiere_aviso,
            "mensajeAdmin": "\n".join(lineas), "claveAlerta": clave,
            "requiere_confirmacion_humana": True,
        }
