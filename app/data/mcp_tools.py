"""Herramientas (tools) que los agentes usan para leer los demás microservicios.
Los agentes NO hacen SQL: solo invocan estas tools vía HTTP (equivalente MCP para desarrollo local)."""
from datetime import date, timedelta

import httpx

from app.data import comedor_http


class McpToolClient:
    def __init__(self):
        self.menu = comedor_http.url("menu")

    def _lista(self, ruta: str) -> list:
        try:
            r = httpx.get(f"{self.menu}{ruta}", timeout=5)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    # --- menu-inventario tools ---
    def ver_stock_insumo(self) -> list:
        return self._lista("/insumos")

    def ver_stock_bajo(self) -> list:
        return self._lista("/insumos/stock-bajo")

    def lotes_por_vencer(self, dias: int = 7) -> list:
        """Devuelve lotes cuyo `vence` ≤ hoy+dias. Usa /insumos y lee lotes anidados."""
        insumos = self.ver_stock_insumo()
        limite = date.today() + timedelta(days=dias)
        por_vencer = []
        for ins in insumos:
            for lote in (ins.get("lotes") or []):
                v = (lote.get("vencimiento") or {}).get("fecha") or lote.get("vence")
                if not v:
                    continue
                try:
                    fv = date.fromisoformat(str(v)[:10])
                except Exception:
                    continue
                if fv <= limite:
                    dias_rest = (fv - date.today()).days
                    por_vencer.append({
                        "insumoId": ins.get("id"),
                        "nombre": ins.get("nombre"),
                        "cantidad": (lote.get("cantidad") or {}).get("valor"),
                        "unidad": ins.get("unidad"),
                        "vence": str(v)[:10],
                        "diasRestantes": dias_rest,
                    })
        return sorted(por_vencer, key=lambda x: x["diasRestantes"])
