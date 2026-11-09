"""Notificaciones push: el teléfono registra su token y aquí se elige a quién avisar.

El envío a Firebase Cloud Messaging lo hace n8n (flujo «notificar», SPEC §9); la credencial de Firebase vive allá.
Un push es "lo mejor posible": si n8n o Firebase no responden, el sistema sigue funcionando y el aviso sigue llegando
por Telegram. Los tokens que Firebase marca como inválidos se borran solos.
"""
import time

from app.application.ports.externos import MotorFlujos
from app.application.ports.repositorios import RepositorioDispositivos
from app.domain import push as dom
from app.domain.errores import DatoInvalido, NoConfigurado


class ServicioPush:
    def __init__(self, dispositivos: RepositorioDispositivos, flujos: MotorFlujos):
        self._dispositivos = dispositivos
        self._flujos = flujos
        self._estado = {"ultimo_envio": None, "ultimo_error": None, "enviados": 0}

    def configurado(self) -> bool:
        return self._flujos.activo()

    # ----------------------------- teléfonos -----------------------------

    def registrar_dispositivo(self, token: str, usuario_token: str | None, roles_token: list[str],
                              usuario_cuerpo: str | None, roles_cuerpo: list[str], plataforma: str) -> dict:
        """Guarda el token de este teléfono para el usuario que inició sesión (los roles salen del token, no del cuerpo)."""
        dom.validar_token_dispositivo(token)
        usuario, roles = dom.titular(usuario_token, roles_token, usuario_cuerpo, roles_cuerpo)
        self._dispositivos.registrar(token, usuario, roles, plataforma[:20])
        return {"ok": True, "usuario": usuario, "roles": roles}

    def dar_de_baja(self, token: str) -> dict:
        """Al cerrar sesión: este teléfono deja de recibir avisos de ese usuario."""
        return {"ok": self._dispositivos.dar_de_baja(token)}

    def prueba(self, usuario: str | None, roles: list[str], titulo: str, cuerpo: str) -> dict:
        """Manda una notificación de prueba a un usuario o a un rol (para comprobar que todo está conectado)."""
        if not self.configurado():
            raise NoConfigurado("El envío de push no está configurado (falta N8N_URL)")
        if usuario:
            return self.enviar_a_usuario(usuario, titulo, cuerpo, {"tipo": "prueba"})
        if roles:
            return self.enviar_a_roles(roles, titulo, cuerpo, {"tipo": "prueba"})
        raise DatoInvalido("Indica un usuario o una lista de roles")

    # ----------------------------- envío -----------------------------

    def _enviar_fcm(self, token: str, titulo: str, cuerpo: str, datos: dict[str, str]) -> tuple[bool, bool]:
        """(se entregó a Firebase, el token ya no sirve). No lanza."""
        if not self.configurado():
            return False, False
        try:
            r = self._flujos.llamar("notificar", {"canal": "push", "token": token, "titulo": titulo, "cuerpo": cuerpo, "datos": datos,
                                                  "vigencia": dom.VIGENCIA, "canalAndroid": dom.CANAL})
        except Exception as e:                                   # n8n apagado o sin red
            self._estado["ultimo_error"] = f"{getattr(e, 'tipo', type(e).__name__)}: {str(e)[:120]}"
            return False, False
        if r.get("ok"):
            return True, False
        self._estado["ultimo_error"] = str(r.get("description"))[:160]
        return False, bool(r.get("tokenInvalido"))

    def _despachar(self, destinos: list[dict], titulo: str, cuerpo: str, datos: dict | None) -> dict:
        datos = dom.datos_como_texto(datos)
        vistos, enviados, fallidos, borrados = set(), 0, 0, 0
        for d in destinos:
            if d["token"] in vistos:
                continue
            vistos.add(d["token"])
            ok, muerto = self._enviar_fcm(d["token"], titulo[:100], cuerpo[:400], datos)
            if ok:
                enviados += 1
            else:
                fallidos += 1
            if muerto and self._dispositivos.dar_de_baja(d["token"]):
                borrados += 1
        if enviados:
            self._estado["ultimo_envio"] = time.time()
            self._estado["enviados"] += enviados
        return {"destinatarios": len(vistos), "enviados": enviados, "fallidos": fallidos, "tokensBorrados": borrados,
                "configurado": self.configurado()}

    def enviar_a_roles(self, roles: list[str], titulo: str, cuerpo: str, datos: dict | None = None) -> dict:
        return self._despachar(self._dispositivos.de_roles(roles), titulo, cuerpo, datos)

    def enviar_a_usuario(self, usuario: str, titulo: str, cuerpo: str, datos: dict | None = None) -> dict:
        return self._despachar(self._dispositivos.de_usuario(usuario), titulo, cuerpo, datos)

    def estado(self) -> dict:
        return {"configurado": self.configurado(), "dispositivos": self._dispositivos.contar(), **self._estado}
