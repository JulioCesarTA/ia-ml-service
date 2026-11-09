"""Los 7 indicadores clave (caso de uso): carga los conjuntos de datos y los calcula en el dominio."""
from app.application.reportes.fuentes import FuentesReportes
from app.domain.analitica import kpis as dom


class ServicioKpis:
    def __init__(self, fuentes: FuentesReportes):
        self._fuentes = fuentes

    def calcular(self) -> dict:
        return dom.calcular(self._fuentes.cargar)
