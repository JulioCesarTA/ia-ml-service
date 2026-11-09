"""Programación de los agentes (caso de uso): guarda los horarios, dice cuándo toca y ejecuta cada agente.

El reloj que despierta cada 20 segundos es un adaptador de entrada (ver infrastructure/adapters/inbound/tareas).
"""
import json
import time
from datetime import datetime

from app.application.agentes.agentes import InventarioComprasAgent, MonitorComedorAgent, PlanificadorMenuAgent
from app.application.agentes.avisos import ServicioAvisos
from app.application.ports.repositorios import RepositorioConfig
from app.domain import horarios as dom
from app.domain.horarios import AGENTES


class Programador:
    AGENTES = AGENTES

    def __init__(self, config: RepositorioConfig, avisos: ServicioAvisos, inventario: InventarioComprasAgent,
                 planificador: PlanificadorMenuAgent, monitor: MonitorComedorAgent):
        self._config = config
        self._avisos = avisos
        self._inventario = inventario
        self._planificador = planificador
        self._monitor = monitor

    def horario(self, nombre: str) -> dict:
        guardado = self._config.leer(f"horario:{nombre}")
        return {**dom.DEFECTO[nombre], **(json.loads(guardado) if guardado else {})}

    def guardar(self, nombre: str, h: dict) -> dict:
        v = dom.validar(h)
        self._config.escribir(f"horario:{nombre}", json.dumps(v))
        self._config.escribir(f"ultima:{nombre}", str(time.time()))      # cuenta desde ahora: no dispara de inmediato
        return v

    def ultima(self, nombre: str) -> float | None:
        v = self._config.leer(f"ultima:{nombre}")
        return float(v) if v else None

    def proxima(self, nombre: str, ahora: datetime | None = None) -> datetime | None:
        h, ahora = self.horario(nombre), ahora or datetime.now()
        if not h["activo"]:
            return None
        return dom.proxima(h, self.ultima(nombre) if h["modo"] == "cada" else None, ahora)

    def estado(self) -> dict:
        out = {}
        for n in AGENTES:
            u, p = self.ultima(n), self.proxima(n)
            out[n] = {"horario": self.horario(n),
                      "ultima": datetime.fromtimestamp(u).isoformat(timespec="minutes") if u else None,
                      "proxima": p.isoformat(timespec="minutes") if p else None}
        return out

    def _toca(self, nombre: str, ahora: datetime) -> bool:
        h = self.horario(nombre)
        if not h["activo"]:
            return False
        r = dom.toca(h, self.ultima(nombre), ahora)
        if r is None:                                          # primera vez: no se ejecuta retroactivamente
            self._config.escribir(f"ultima:{nombre}", str(ahora.timestamp()))
            return False
        return r

    def ejecutar(self, nombre: str) -> None:
        if nombre == "inventario-compras":
            self._avisos.proponer_inventario(self._inventario.run("Ejecución programada", {}))
        elif nombre == "planificador-menu":
            self._avisos.proponer_menu(self._planificador.run("Ejecución programada", {}))
        else:
            self._avisos.avisar_monitor(self._monitor.run("Ejecución programada", {}))

    def revisar(self, ahora: datetime) -> None:
        """Una vuelta del reloj: ejecuta los agentes a los que les toca."""
        for n in AGENTES:
            try:
                if self._toca(n, ahora):
                    self._config.escribir(f"ultima:{n}", str(time.time()))      # antes de correr: un fallo no lo repite sin parar
                    self.ejecutar(n)
                    print(f"[programador] {n} ejecutado", flush=True)
            except Exception as e:
                print(f"[programador] {n}: {e}", flush=True)
