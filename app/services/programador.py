"""Programación de los agentes: cada cuánto, o a qué día y hora, se ejecutan solos. Se edita desde el panel.

Modos:
  cada     -> cada N minutos
  diario   -> todos los días a HH:MM
  semanal  -> los días elegidos (0=lunes ... 6=domingo) a HH:MM
Las horas son las del servidor (TZ=America/La_Paz).
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

from app.data import repo_config
from app.services.agentes import avisos
from app.services.agentes.inventario_compras_agent import InventarioComprasAgent
from app.services.agentes.monitor_comedor_agent import MonitorComedorAgent
from app.services.agentes.planificador_menu_agent import PlanificadorMenuAgent

AGENTES = ("inventario-compras", "planificador-menu", "monitor-comedor")
TODOS = [0, 1, 2, 3, 4, 5, 6]
DEFECTO = {
    "inventario-compras": {"activo": True, "modo": "cada", "cadaMin": 15, "hora": "08:00", "dias": TODOS},
    "planificador-menu": {"activo": True, "modo": "semanal", "cadaMin": 60, "hora": "08:00", "dias": [4]},
    "monitor-comedor": {"activo": True, "modo": "diario", "cadaMin": 60, "hora": "08:00", "dias": TODOS},
}
MIN_CADA = 5


def horario(nombre: str) -> dict:
    guardado = repo_config.leer(f"horario:{nombre}")
    return {**DEFECTO[nombre], **(json.loads(guardado) if guardado else {})}


def validar(h: dict) -> dict:
    modo = h.get("modo")
    if modo not in ("cada", "diario", "semanal"):
        raise ValueError("Modo inválido")
    cada = int(h.get("cadaMin") or 0)
    if modo == "cada" and not (MIN_CADA <= cada <= 60 * 24 * 30):
        raise ValueError(f"Elige un intervalo de al menos {MIN_CADA} minutos (máximo 30 días)")
    hora = str(h.get("hora") or "")
    if modo != "cada" and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora):
        raise ValueError("La hora debe tener formato HH:MM (24 h)")
    dias = sorted({int(d) for d in (h.get("dias") or [])})
    if modo == "semanal" and (not dias or any(d not in TODOS for d in dias)):
        raise ValueError("Elige al menos un día de la semana")
    return {"activo": bool(h.get("activo", True)), "modo": modo, "cadaMin": cada or 60,
            "hora": hora or "08:00", "dias": dias or TODOS}


def guardar(nombre: str, h: dict) -> dict:
    v = validar(h)
    repo_config.escribir(f"horario:{nombre}", json.dumps(v))
    repo_config.escribir(f"ultima:{nombre}", str(time.time()))      # cuenta desde ahora: no dispara de inmediato
    return v


def ultima(nombre: str) -> float | None:
    v = repo_config.leer(f"ultima:{nombre}")
    return float(v) if v else None


def _hm(h: dict) -> tuple[int, int]:
    hh, mm = h["hora"].split(":")
    return int(hh), int(mm)


def _ultima_programada(h: dict, ahora: datetime) -> datetime | None:
    hh, mm = _hm(h)
    for atras in range(8):
        dia = (ahora - timedelta(days=atras)).date()
        if h["modo"] == "semanal" and dia.weekday() not in h["dias"]:
            continue
        dt = datetime(dia.year, dia.month, dia.day, hh, mm)
        if dt <= ahora:
            return dt
    return None


def proxima(nombre: str, ahora: datetime | None = None) -> datetime | None:
    h, ahora = horario(nombre), ahora or datetime.now()
    if not h["activo"]:
        return None
    if h["modo"] == "cada":
        u = ultima(nombre)
        return datetime.fromtimestamp(u) + timedelta(minutes=h["cadaMin"]) if u else ahora
    hh, mm = _hm(h)
    for adelante in range(9):
        dia = (ahora + timedelta(days=adelante)).date()
        if h["modo"] == "semanal" and dia.weekday() not in h["dias"]:
            continue
        dt = datetime(dia.year, dia.month, dia.day, hh, mm)
        if dt > ahora:
            return dt
    return None


def estado() -> dict:
    out = {}
    for n in AGENTES:
        u, p = ultima(n), proxima(n)
        out[n] = {"horario": horario(n),
                  "ultima": datetime.fromtimestamp(u).isoformat(timespec="minutes") if u else None,
                  "proxima": p.isoformat(timespec="minutes") if p else None}
    return out


def _toca(nombre: str, ahora: datetime) -> bool:
    h = horario(nombre)
    if not h["activo"]:
        return False
    u = ultima(nombre)
    if h["modo"] == "cada":
        return u is None or ahora.timestamp() - u >= h["cadaMin"] * 60
    if u is None:                                          # primera vez: no se ejecuta retroactivamente
        repo_config.escribir(f"ultima:{nombre}", str(ahora.timestamp()))
        return False
    prog = _ultima_programada(h, ahora)
    return bool(prog and u < prog.timestamp())


def ejecutar(nombre: str) -> None:
    if nombre == "inventario-compras":
        avisos.proponer_inventario(InventarioComprasAgent().run("Ejecución programada", {}))
    elif nombre == "planificador-menu":
        avisos.proponer_menu(PlanificadorMenuAgent().run("Ejecución programada", {}))
    else:
        avisos.avisar_monitor(MonitorComedorAgent().run("Ejecución programada", {}))


def _bucle() -> None:
    time.sleep(int(os.getenv("VIGILANCIA_INICIO_S", "45")))
    while True:
        ahora = datetime.now()
        for n in AGENTES:
            try:
                if _toca(n, ahora):
                    repo_config.escribir(f"ultima:{n}", str(time.time()))      # antes de correr: un fallo no lo repite sin parar
                    ejecutar(n)
                    print(f"[programador] {n} ejecutado", flush=True)
            except Exception as e:
                print(f"[programador] {n}: {e}", flush=True)
        time.sleep(20)


def iniciar() -> None:
    if os.getenv("VIGILANCIA", "on") == "on":
        threading.Thread(target=_bucle, daemon=True, name="programador-agentes").start()
