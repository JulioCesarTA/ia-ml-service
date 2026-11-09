"""Entrada de Telegram por long-polling (getUpdates): no hace falta IP pública ni webhook.

Con TELEGRAM_RECEPCION=n8n la recepción la hace n8n (POST /agentes/telegram/evento) y aquí solo se registran los
comandos. También corren aquí el envío de la cola de avisos y la revisión de pagos pendientes del asistente.
"""
import threading
import time

from app.application.asistente import Asistente
from app.application.ports.errores import ErrorDeRed
from app.application.telegram_bot import ServicioTelegram


def _bucle_envio(bot: ServicioTelegram) -> None:
    despertar = bot.cola.despertar
    while True:
        try:
            bot.vaciar_cola()
        except Exception as e:
            bot.anotar_error(str(e)[:150])
        despertar.wait(timeout=10)
        despertar.clear()


def _bucle_recepcion(bot: ServicioTelegram, recepcion_n8n: bool) -> None:
    comandos_listos = False
    while True:
        if not bot.configurado():
            time.sleep(30)
            continue
        try:
            if not comandos_listos:
                bot.registrar_comandos()
                comandos_listos = True
            if recepcion_n8n:
                time.sleep(60)
                continue
            bot.recibir_actualizaciones()
        except ErrorDeRed as e:
            bot.anotar_error(f"sin conexión: {str(e)[:80]}")
            time.sleep(10)
        except Exception as e:
            bot.anotar_error(str(e)[:150])
            time.sleep(10)


def _bucle_pagos(bot: ServicioTelegram, asistente: Asistente) -> None:
    while True:
        try:
            if bot.configurado():
                asistente.revisar_pagos()
        except Exception as e:
            print(f"[telegram-pagos] {e}", flush=True)
        time.sleep(8)


def iniciar(bot: ServicioTelegram, asistente: Asistente, recepcion_n8n: bool) -> None:
    threading.Thread(target=_bucle_envio, args=(bot,), daemon=True, name="telegram-envio").start()
    threading.Thread(target=_bucle_recepcion, args=(bot, recepcion_n8n), daemon=True, name="telegram-recepcion").start()
    threading.Thread(target=_bucle_pagos, args=(bot, asistente), daemon=True, name="telegram-pagos").start()
