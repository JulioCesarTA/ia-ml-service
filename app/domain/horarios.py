"""Horarios de los agentes: cada cuánto, o a qué día y hora, se ejecutan solos.

Modos:
  cada     -> cada N minutos
  diario   -> todos los días a HH:MM
  semanal  -> los días elegidos (0=lunes ... 6=domingo) a HH:MM
Las horas son las del servidor (TZ=America/La_Paz).
"""
import re
from datetime import datetime, timedelta

AGENTES = ("inventario-compras", "planificador-menu", "monitor-comedor")
TODOS = [0, 1, 2, 3, 4, 5, 6]
DEFECTO = {
    "inventario-compras": {"activo": True, "modo": "cada", "cadaMin": 15, "hora": "08:00", "dias": TODOS},
    "planificador-menu": {"activo": True, "modo": "semanal", "cadaMin": 60, "hora": "08:00", "dias": [4]},
    "monitor-comedor": {"activo": True, "modo": "diario", "cadaMin": 60, "hora": "08:00", "dias": TODOS},
}
MIN_CADA = 5


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


def _hm(h: dict) -> tuple[int, int]:
    hh, mm = h["hora"].split(":")
    return int(hh), int(mm)


def ultima_programada(h: dict, ahora: datetime) -> datetime | None:
    hh, mm = _hm(h)
    for atras in range(8):
        dia = (ahora - timedelta(days=atras)).date()
        if h["modo"] == "semanal" and dia.weekday() not in h["dias"]:
            continue
        dt = datetime(dia.year, dia.month, dia.day, hh, mm)
        if dt <= ahora:
            return dt
    return None


def proxima(h: dict, ultima: float | None, ahora: datetime) -> datetime | None:
    if not h["activo"]:
        return None
    if h["modo"] == "cada":
        return datetime.fromtimestamp(ultima) + timedelta(minutes=h["cadaMin"]) if ultima else ahora
    hh, mm = _hm(h)
    for adelante in range(9):
        dia = (ahora + timedelta(days=adelante)).date()
        if h["modo"] == "semanal" and dia.weekday() not in h["dias"]:
            continue
        dt = datetime(dia.year, dia.month, dia.day, hh, mm)
        if dt > ahora:
            return dt
    return None


def toca(h: dict, ultima: float | None, ahora: datetime) -> bool | None:
    """True si toca ejecutar. None en la primera vez de un horario diario/semanal: no se ejecuta retroactivamente,
    solo se anota `ahora` como última ejecución."""
    if not h["activo"]:
        return False
    if h["modo"] == "cada":
        return ultima is None or ahora.timestamp() - ultima >= h["cadaMin"] * 60
    if ultima is None:
        return None
    prog = ultima_programada(h, ahora)
    return bool(prog and ultima < prog.timestamp())
