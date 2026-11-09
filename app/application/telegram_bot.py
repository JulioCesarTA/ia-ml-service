"""Telegram del comedor (caso de uso).

- Los avisos para aprobar llegan SOLO a los chats de usuarios con rol administrador (vinculados por correo).
- Los mensajes se guardan primero en una cola local: si no hay internet salen solos al volver la red.
- Se reciben mensajes y botones con long-polling (getUpdates, ver el adaptador de entrada) o los entrega n8n
  (TELEGRAM_RECEPCION=n8n): entonces se llama a `procesar_evento` y se devuelven las acciones que n8n debe ejecutar.
- La conversación con cada persona (menú, quién soy, reservar y pagar) vive en `asistente`.
"""
import contextvars
import time

from app.application.cola_mensajes import ColaMensajes
from app.application.identidad import ServicioIdentidad
from app.application.ports.errores import ErrorDeRed
from app.application.ports.externos import ClienteTelegram
from app.application.ports.repositorios import RepositorioConfig
from app.application.propuestas import ServicioPropuestas
from app.domain import propuestas as dom_propuestas

_SALIENTES = {"sendMessage", "answerCallbackQuery", "editMessageReplyMarkup", "deleteMessage"}
COMANDOS = [("start", "Mostrar el menú principal"), ("menu", "Ver el menú de comidas"), ("quiensoy", "Ver con qué cuenta estoy"),
            ("reservar", "Reservar una ración"), ("cambiar", "Cerrar sesión y entrar con otra cuenta")]


def boton(texto: str, data: str) -> dict:
    return {"text": texto, "callback_data": data}


def botones_propuesta(pid: str) -> list[list[dict]]:
    return [[boton("✅ Aprobar", f"ap:{pid}"), boton("❌ Rechazar", f"re:{pid}")]]


class ServicioTelegram:
    boton = staticmethod(boton)
    botones_propuesta = staticmethod(botones_propuesta)

    def __init__(self, cliente: ClienteTelegram, cola: ColaMensajes, identidad: ServicioIdentidad,
                 propuestas: ServicioPropuestas, config: RepositorioConfig):
        self._cliente = cliente
        self.cola = cola
        self._identidad = identidad
        self._propuestas = propuestas
        self._config = config
        self.asistente = None                   # la conversación (se conecta al armar la aplicación)
        self._estado = {"ultimo_error": None, "ultimo_envio": None}
        self._captura: contextvars.ContextVar[list | None] = contextvars.ContextVar("captura_telegram", default=None)

    def configurado(self) -> bool:
        return self._cliente.configurado()

    def _api(self, metodo: str, _espera: float = 15, **payload):
        acciones = self._captura.get()
        if acciones is not None and metodo in _SALIENTES:     # n8n ejecuta estas llamadas
            acciones.append({"metodo": metodo, "datos": payload})
            return {}
        return self._cliente.llamar(metodo, _espera, **payload)

    def anotar_error(self, texto: str) -> None:
        self._estado["ultimo_error"] = texto

    # ----------------------------- envío directo (conversación) -----------------------------

    def enviar(self, chat: str, texto: str, botones: list[list[dict]] | None = None) -> dict:
        datos = {"chat_id": chat, "text": texto[:4000]}
        if botones:
            datos["reply_markup"] = {"inline_keyboard": botones}
        return self._api("sendMessage", **datos)

    def enviar_foto(self, chat: str, png: bytes, pie: str = "") -> None:
        self._cliente.enviar_foto(chat, png, pie)

    def enviar_documento_url(self, chat: str, url: str, pie: str = "") -> None:
        self._api("sendDocument", _espera=40, chat_id=chat, document=url, caption=pie[:1000])

    def responder_boton(self, callback_id: str, texto: str | None = None) -> None:
        if texto is None:
            self._api("answerCallbackQuery", callback_query_id=callback_id)
        else:
            self._api("answerCallbackQuery", callback_query_id=callback_id, text=texto)

    def borrar(self, chat: str, message_id: int) -> None:
        try:
            self._api("deleteMessage", chat_id=chat, message_id=message_id)
        except Exception:
            pass

    # ----------------------------- cola de avisos al administrador -----------------------------

    def encolar(self, texto: str, propuesta_id: str | None = None, chat: str | None = None) -> None:
        """Guarda el mensaje. Sin `chat`, va a todos los administradores vinculados (espera si aún no hay ninguno)."""
        self.cola.encolar(texto, propuesta_id, chat)

    def estado(self) -> dict:
        en_cola = self.cola.repo.mensajes_en_cola()
        admins = self._identidad.chats_admin()
        return {
            "configurado": self.configurado(),
            "vinculado": bool(admins),
            "administradores": len(admins),
            "chatsVinculados": len(self._identidad.chats_listos()),
            "mensajesEnCola": en_cola,
            "ultimoEnvio": self._estado["ultimo_envio"],
            "ultimoError": self._estado["ultimo_error"],
        }

    def vaciar_cola(self) -> None:
        if not self.configurado():
            return
        repo = self.cola.repo
        admins = self._identidad.chats_admin()
        for f in repo.cola():
            destino = f["chat_id"]
            if destino is None:
                if not admins:
                    continue                              # espera a que un administrador vincule su chat
                repo.repartir(f, admins)
                self.cola.despertar.set()
                continue
            pid = f["propuesta_id"]
            p = self._propuestas.obtener(pid) if pid else None
            con_botones = bool(p and p["estado"] == dom_propuestas.PENDIENTE)     # si ya se resolvió en el panel, sin botones
            try:
                self.enviar(destino, f["texto"], botones_propuesta(pid) if con_botones else None)
                self._estado["ultimo_envio"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._estado["ultimo_error"] = None
                borrar_fila = True
            except ErrorDeRed as e:                         # sin internet: se reintenta luego
                self._estado["ultimo_error"] = f"sin conexión: {str(e)[:80]}"
                return
            except Exception as e:                          # Telegram rechazó el mensaje: reintentos limitados
                self._estado["ultimo_error"] = str(e)[:150]
                borrar_fila = f["intentos"] >= 4
                if not borrar_fila:
                    repo.sumar_intento(f["id"])
            if borrar_fila:
                repo.quitar_de_cola(f["id"])

    # ----------------------------- recepción -----------------------------

    def _boton_propuesta(self, cb: dict) -> None:
        cid = str(cb["message"]["chat"]["id"])
        if not self._identidad.es_admin(cid):
            self._api("answerCallbackQuery", callback_query_id=cb["id"], text="Solo un administrador puede aprobar o rechazar")
            return
        accion, _, pid = cb["data"].partition(":")
        previa = self._propuestas.obtener(pid)
        if previa is None:
            self._api("answerCallbackQuery", callback_query_id=cb["id"], text="La propuesta ya no existe")
            return
        if previa["estado"] != dom_propuestas.PENDIENTE:
            self._api("answerCallbackQuery", callback_query_id=cb["id"], text=f"Ya estaba {previa['estado'].lower()}")
            res = previa
        else:
            self._api("answerCallbackQuery", callback_query_id=cb["id"], text="Procesando…")
            res = self._propuestas.resolver(pid, accion == "ap", "Telegram")
        try:
            self._api("editMessageReplyMarkup", chat_id=cid, message_id=cb["message"]["message_id"], reply_markup={"inline_keyboard": []})
        except Exception:
            pass
        self.encolar(dom_propuestas.texto_resultado(res))

    def procesar(self, u: dict) -> None:
        if "callback_query" in u:
            cb = u["callback_query"]
            if cb.get("data", "")[:3] in ("ap:", "re:"):
                self._boton_propuesta(cb)
            else:
                self.asistente.boton(cb)
        elif "message" in u:
            self.asistente.mensaje(u["message"])

    def procesar_evento(self, u: dict) -> list[dict]:
        """Procesa un update de Telegram y devuelve las llamadas a la API de Telegram que debe hacer quien lo envió (n8n)."""
        acciones: list[dict] = []
        marca = self._captura.set(acciones)
        try:
            self.procesar(u)
        finally:
            self._captura.reset(marca)
        return acciones

    def registrar_comandos(self) -> None:
        self._api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMANDOS])

    def recibir_actualizaciones(self) -> None:
        """Una vuelta de long-polling: procesa lo nuevo y recuerda la posición. Lanza ErrorDeRed si no hay conexión."""
        offset = int(self._config.leer("offset") or 0)
        for u in self._api("getUpdates", _espera=40, timeout=25, offset=offset, allowed_updates=["message", "callback_query"]):
            self._config.escribir("offset", str(u["update_id"] + 1))
            try:
                self.procesar(u)
            except ErrorDeRed:
                raise
            except Exception as e:
                self._estado["ultimo_error"] = str(e)[:150]
