"""Puertos de salida hacia sistemas externos: MCP, CQRS, Keycloak, n8n, Telegram, S3, clima y visión (TensorFlow)."""
from typing import Any, Protocol


class HerramientasMcp(Protocol):
    """Herramientas MCP de los otros microservicios. Si el servicio no responde devuelven vacío."""

    def consultar_menu(self, turno: str) -> list: ...

    def ver_stock_insumo(self) -> list: ...

    def ver_stock_bajo(self) -> list: ...

    def lotes_por_vencer(self, dias: int = 7) -> list: ...

    def sugerir_cantidad_cocinar(self, turno: str) -> list: ...

    def crear_orden_compra_borrador(self) -> list: ...

    def publicar_menu(self, fecha: str, turno: str, platos: list[dict]) -> bool: ...

    def consultar_beca(self, estudiante: str) -> dict: ...


class ConsultasLectura(Protocol):
    """Base de lectura CQRS: solo consultas predefinidas y parametrizadas (SPEC §10)."""

    def consulta_predefinida(self, nombre: str, params: dict) -> list[dict]: ...


class ProveedorIdentidad(Protocol):
    """Keycloak: usuarios, roles y contraseñas."""

    def usuario_por_email(self, email: str) -> dict | None: ...

    def verificar_password(self, username: str, password: str) -> bool: ...


class MotorFlujos(Protocol):
    """n8n: envía las notificaciones (Telegram, push) y ejecuta los flujos. Lanza ErrorDeRed si no responde."""

    def activo(self) -> bool: ...

    def llamar(self, webhook: str, cuerpo: dict, espera: float = 20) -> dict: ...


class ClienteTelegram(Protocol):
    """Bot API de Telegram (directo o a través de n8n). Lanza ErrorDeRed si no hay conexión."""

    def configurado(self) -> bool: ...

    def llamar(self, metodo: str, espera: float = 15, **payload) -> Any: ...

    def enviar_foto(self, chat: str, png: bytes, pie: str) -> None: ...


class AlmacenObjetos(Protocol):
    """Bucket de fotos y respaldos (S3). Si no está configurado, `subir`/`existe` devuelven False."""

    def configurado(self) -> bool: ...

    def subir(self, clave: str, datos: bytes, content_type: str = "image/jpeg") -> bool: ...

    def existe(self, clave: str) -> bool: ...

    def url_subida(self, clave: str, content_type: str = "image/jpeg", segundos: int = 600) -> str: ...

    def url_lectura(self, clave: str, segundos: int = 900) -> str | None: ...


class ApiClima(Protocol):
    """Temperatura diaria media. Lanza excepción si no hay red."""

    def temperatura_historica(self, lat: float, lon: float, desde: str, hasta: str) -> dict[str, float]: ...

    def temperatura_diaria(self, lat: float, lon: float) -> dict[str, float]: ...


class ProcesadorImagenes(Protocol):
    """La red convolucional (TensorFlow) y la lectura de imágenes. `cargar` devuelve una imagen opaca para el núcleo."""

    def nombre_modelo(self) -> str: ...

    def cargar(self, datos: bytes) -> Any: ...

    def zonas(self, imagen: Any) -> tuple[Any, Any]:
        """(descriptor de cada zona [REJ*REJ, DIM], 'aspecto de comida' de cada zona [REJ*REJ]) como arreglos numpy."""
        ...

    def zonas_completas(self, imagen: Any) -> tuple[Any, Any, Any, Any]:
        """Como `zonas`, más la saturación y la textura crudas de cada zona (entrada de la red de sectores)."""
        ...

    def modelo_sectores(self) -> dict | None:
        """Pesos de la red que reconoce los sectores de la bandeja (None si no hay modelo entrenado)."""
        ...

    def jpeg_reducido(self, imagen: Any) -> bytes:
        """La foto achicada a 900 px como máximo, en JPEG calidad 85."""
        ...


class ArchivosVision(Protocol):
    """Archivos locales de visión: fotos (respaldo en disco) y prototipos de cada referencia."""

    def guardar_foto(self, carpeta: str, fid: str, jpeg: bytes) -> None: ...

    def ruta_foto(self, carpeta: str, fid: str) -> str | None: ...

    def guardar_prototipos(self, rid: str, comida: Any, fondo: Any) -> None: ...

    def cargar_prototipos(self, rid: str) -> dict:
        """{'comida': array, 'fondo': array}. Lanza excepción si no existen."""
        ...

    def hay_prototipos(self, rid: str) -> bool: ...
