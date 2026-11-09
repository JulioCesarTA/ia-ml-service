"""Carga de los datos reales del comedor para los reportes (de cada servicio, solo lectura).

Cada conjunto se devuelve como una tabla (DataFrame) con las columnas del catálogo (ver dominio `reportes.tablas`).
Los resultados se guardan unos segundos para que consultas seguidas sean instantáneas.
"""
import threading
import time

import pandas as pd

from app.application.analitica.datos import DatosMenus
from app.application.ports.comedor import LectorDatosComedor
from app.application.ports.repositorios import RepositorioVision
from app.domain.reportes import tablas

TTL = 10.0
TTL_GRANDES = 60.0          # reservas y pagos pueden ser miles de filas: se leen una vez por minuto


class FuenteNoDisponible(Exception):
    pass


class FuentesReportes:
    def __init__(self, lector: LectorDatosComedor, repo_vision: RepositorioVision, datos: DatosMenus):
        self._lector = lector
        self._vision = repo_vision
        self._datos = datos
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self.CARGADORES = {"reservas": self._reservas, "pagos": self._pagos, "estudiantes": self._estudiantes,
                           "becas": self._becas, "menus": self._menus, "insumos": self._insumos,
                           "desperdicio": self._desperdicio, "asistencia": self._asistencia}

    def _json(self, servicio: str, ruta: str):
        url = self._lector.direccion(servicio, ruta)
        try:
            return self._lector.leer_json(url)
        except Exception as e:
            raise FuenteNoDisponible(f"No pude leer los datos ({url.split('/')[2]}): {str(e)[:80]}")

    # ----------------------------- conjuntos -----------------------------

    def _reservas(self) -> pd.DataFrame:
        return tablas.reservas(self._json("comensales", "/analitica/reservas"))

    def _pagos(self) -> pd.DataFrame:
        return tablas.pagos(self._json("pagos", "/pagos"))

    def _becas(self) -> pd.DataFrame:
        return tablas.becas(self._json("comensales", "/analitica/becas"))

    def _asistencia(self) -> pd.DataFrame:
        return tablas.asistencia(self._json("comensales", "/analitica/asistencia"))

    def _estudiantes(self) -> pd.DataFrame:
        filas = self._json("comensales", "/estudiantes")
        return tablas.estudiantes(filas, self.cargar("becas"), self.cargar("reservas"), self.cargar("pagos"))

    def _menus(self) -> pd.DataFrame:
        filas = self._datos.filas(ttl=TTL)
        if not filas and not self._datos.fuente_ok():
            raise FuenteNoDisponible("No pude leer los menús (servicio de menús sin respuesta)")
        return tablas.menus(filas)

    def _insumos(self) -> pd.DataFrame:
        return tablas.insumos(self._json("menu", "/insumos"))

    def _desperdicio(self) -> pd.DataFrame:
        return tablas.desperdicio(self._vision.todas_las_bandejas())

    def invalidar(self) -> None:
        with self._lock:
            self._cache.clear()

    def cargar(self, dataset: str) -> pd.DataFrame:
        with self._lock:
            hit = self._cache.get(dataset)
            if hit and time.time() - hit[0] < (TTL_GRANDES if dataset in ("reservas", "pagos") else TTL):
                return hit[1].copy()
        df = self.CARGADORES[dataset]()
        with self._lock:
            self._cache[dataset] = (time.time(), df)
        return df.copy()
