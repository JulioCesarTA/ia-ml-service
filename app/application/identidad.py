"""Quién es quien escribe al bot: correo institucional -> usuario y rol (Keycloak), con el padrón como respaldo."""
from app.application.ports.comedor import ServicioReservas
from app.application.ports.externos import ProveedorIdentidad
from app.application.ports.repositorios import RepositorioChats
from app.domain import identidad as dom
from app.domain.identidad import PRIVILEGIADOS, rol_principal  # noqa: F401  (reexportados para los casos de uso)


class ServicioIdentidad:
    PRIVILEGIADOS = PRIVILEGIADOS

    def __init__(self, proveedor: ProveedorIdentidad, padron: ServicioReservas, chats: RepositorioChats):
        self._proveedor = proveedor
        self._padron = padron
        self._chats = chats

    @staticmethod
    def rol_principal(roles: list[str]) -> str:
        return rol_principal(roles)

    def buscar_por_email(self, email: str) -> dict | None:
        """{username, nombre, email, roles[], rol} o None. Lanza excepción si no hay conexión con Keycloak."""
        email = email.strip().lower()
        u = self._proveedor.usuario_por_email(email)
        if u:
            return dom.usuario_desde_proveedor(u, email)
        # Respaldo: estudiante del padrón que todavía no tiene cuenta de acceso
        try:
            for e in self._padron.estudiantes():
                if str(e.get("email", "")).strip().lower() == email:
                    return dom.usuario_desde_padron(e, email)
        except Exception:
            pass
        return None

    def verificar_password(self, username: str, password: str) -> bool:
        return self._proveedor.verificar_password(username, password)

    # ----------------------------- chats vinculados -----------------------------

    def chat(self, cid: str) -> dict | None:
        return self._chats.chat(cid)

    def guardar_chat(self, cid: str, **campos) -> dict:
        return self._chats.guardar_chat(cid, **campos)

    def borrar_chat(self, cid: str) -> None:
        self._chats.borrar_chat(cid)

    def chats_listos(self) -> list[dict]:
        return self._chats.chats_listos()

    def chats_admin(self) -> list[str]:
        """Los avisos para aprobar solo llegan (y solo se aceptan) desde chats de usuarios con rol administrador."""
        return [c["chat_id"] for c in self.chats_listos() if "administrador" in c["roles"]]

    def es_admin(self, cid: str) -> bool:
        return cid in self.chats_admin()
