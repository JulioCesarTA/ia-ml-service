"""Errores que los adaptadores de salida traducen para el núcleo (así el núcleo no conoce httpx ni boto3)."""


class ErrorDeRed(Exception):
    """Sin conexión con un servicio externo (n8n, Telegram): el llamador decide reintentar más tarde.

    `tipo` conserva el nombre del error original del adaptador (p. ej. «ConnectError»), que se muestra en los estados.
    """

    def __init__(self, *args, tipo: str | None = None):
        super().__init__(*args)
        self.tipo = tipo or type(self).__name__
