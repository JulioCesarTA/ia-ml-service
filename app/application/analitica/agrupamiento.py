"""Agrupamiento de platos (caso de uso): junta los menús servidos y el desperdicio de las fotos, y agrupa en el dominio."""
from datetime import date
from typing import Callable

from app.application.analitica.datos import DatosMenus
from app.domain.analitica import agrupamiento as dom


class ServicioAgrupamiento:
    def __init__(self, datos: DatosMenus, desperdicio_por_plato: Callable[[], dict[str, float]],
                 min_registros: int = dom.MIN_REGISTROS):
        self._datos = datos
        self._desperdicio_por_plato = desperdicio_por_plato
        self.min_registros = min_registros

    def calcular(self) -> dict:
        return dom.calcular(self._datos.filas(), date.today().isoformat(), self._desperdicio_por_plato,
                            self._datos.fuente_ok, self.min_registros)
