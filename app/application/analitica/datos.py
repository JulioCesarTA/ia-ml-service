"""Datos reales del comedor para los modelos: menús con su cupo y las porciones apartadas (reservas).

Se leen del servicio de menús (fuente única, sin tocar sus bases) y se guardan unos segundos para que el dashboard
pueda actualizarse en tiempo real sin saturar al servicio.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from app.application.ports.comedor import ServicioMenu
from app.domain.analitica import menus as dom
from app.domain.analitica.menus import TURNOS

SEMANAS_ATRAS = 12        # solo se usa si el servicio de menús aún no ofrece el historial por rango
SEMANAS_ADELANTE = 2
ANIOS_HISTORIAL = 3       # los modelos usan hasta 3 años de historial


class DatosMenus:
    def __init__(self, menu: ServicioMenu):
        self._menu = menu
        self._lock = threading.Lock()
        self._cache: dict = {"t": 0.0, "filas": [], "ok": False}

    def _pedir(self, par: tuple[date, str]) -> list[dict]:
        inicio, turno = par
        try:
            return self._menu.menus_semana(turno, inicio.isoformat())
        except Exception:
            return []

    def _historial(self) -> list[dict]:
        """Menús de los últimos 3 años (+ próximas semanas) en una sola llamada; si el servicio es antiguo, semana por semana."""
        hoy = date.today()
        try:
            return self._menu.menus_historial((hoy - timedelta(days=365 * ANIOS_HISTORIAL + 1)).isoformat(),
                                              (hoy + timedelta(weeks=SEMANAS_ADELANTE)).isoformat())
        except Exception:
            inicio = dom.lunes(hoy) - timedelta(weeks=SEMANAS_ATRAS)
            pares = [(inicio + timedelta(weeks=i), t) for i in range(SEMANAS_ATRAS + SEMANAS_ADELANTE + 1) for t in TURNOS]
            with ThreadPoolExecutor(8) as ex:
                return [m for lista in ex.map(self._pedir, pares) for m in lista]

    def invalidar(self) -> None:
        """Olvida lo guardado para que la próxima lectura vaya al servicio de menús."""
        with self._lock:
            self._cache["t"] = 0.0

    def filas(self, ttl: float = 15.0) -> list[dict]:
        """Una fila por (fecha, turno, plato): cupo total y porciones apartadas (suma si hay menús repetidos)."""
        with self._lock:
            if time.time() - self._cache["t"] < ttl:
                return self._cache["filas"]
        menus = self._historial()
        if not menus:                                   # el servicio no respondió: se conserva lo último que se tenía
            with self._lock:
                self._cache["ok"] = False
                return self._cache["filas"]
        out = dom.filas_de_menus(menus)
        with self._lock:
            self._cache.update(t=time.time(), filas=out, ok=True)
        return out

    def firma(self) -> str:
        """Cambia cuando cambian los datos: sirve para reentrenar solo cuando hace falta."""
        return dom.firma(self.filas())

    def fuente_ok(self) -> bool:
        return bool(self._cache["ok"])
