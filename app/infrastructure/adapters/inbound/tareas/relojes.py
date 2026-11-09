"""Disparadores por tiempo (adaptadores de entrada): el programador de los agentes, el respaldo de la base y la
precarga de la red convolucional. Cada uno corre en su propio hilo y solo llama a los casos de uso."""
import threading
import time
from datetime import datetime

from app.application.analitica.vision import ServicioVision
from app.application.programador import Programador
from app.application.respaldo import CADA_SEGUNDOS, ServicioRespaldo


def _bucle_programador(programador: Programador, inicio_s: int) -> None:
    time.sleep(inicio_s)
    while True:
        programador.revisar(datetime.now())
        time.sleep(20)


def iniciar_programador(programador: Programador, activo: bool, inicio_s: int) -> None:
    if activo:
        threading.Thread(target=_bucle_programador, args=(programador, inicio_s), daemon=True, name="programador-agentes").start()


def _bucle_respaldo(respaldo: ServicioRespaldo) -> None:
    time.sleep(90)                                   # deja arrancar el servicio antes del primer respaldo
    while True:
        try:
            respaldo.respaldar()
        except Exception:
            pass                                     # el siguiente intento es en 6 horas; el servicio no se detiene por esto
        time.sleep(CADA_SEGUNDOS)


def iniciar_respaldo(respaldo: ServicioRespaldo) -> None:
    if respaldo.configurado():
        threading.Thread(target=_bucle_respaldo, args=(respaldo,), daemon=True, name="respaldo-s3").start()


def precargar_cnn(vision: ServicioVision) -> None:
    """Precarga la CNN para que la primera foto no espere."""
    threading.Thread(target=vision.nombre_modelo, daemon=True, name="precarga-cnn").start()
