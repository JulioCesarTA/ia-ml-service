"""Copia de los datos del comedor para la app móvil: el celular la guarda y genera los reportes SIN internet.

Cada conjunto sale como columnas + filas (listas), con las fechas como texto AAAA-MM-DD, en el mismo orden que el catálogo.
"""
from datetime import datetime

from app.application.reportes.fuentes import FuentesReportes
from app.domain.reportes import catalogo
from app.domain.reportes.snapshot import permitidos, valor


class ServicioSnapshot:
    def __init__(self, fuentes: FuentesReportes):
        self._fuentes = fuentes

    def registros(self, roles: list[str]) -> tuple[dict[str, list[dict]], dict[str, str]]:
        """{dataset: [fila como diccionario]} con los valores ya normalizados, y los conjuntos que fallaron."""
        datos, errores = {}, {}
        for did in catalogo.DATASETS:
            if did not in permitidos(roles):
                continue
            try:
                df = self._fuentes.cargar(did)
            except Exception as e:
                errores[did] = str(e)[:120]
                continue
            cols = [c["nombre"] for c in catalogo.DATASETS[did]["columnas"]]
            datos[did] = [{c: valor(r[c]) for c in cols} for r in df.to_dict("records")]
        return datos, errores

    def construir(self, roles: list[str]) -> dict:
        datos, errores = self.registros(roles)
        out = {}
        for did, filas in datos.items():
            cols = [c["nombre"] for c in catalogo.DATASETS[did]["columnas"]]
            out[did] = {"columnas": cols, "filas": [[r[c] for c in cols] for r in filas]}
        # El catálogo viaja con los datos: el motor del teléfono lo usa tal cual, sin una copia propia que se desfase.
        permitidos_ = permitidos(roles)
        return {"generado": datetime.now().strftime("%Y-%m-%d %H:%M"), "datasets": out, "errores": errores,
                "catalogo": {did: d for did, d in catalogo.DATASETS.items() if did in permitidos_}}
