"""Errores del negocio que los adaptadores de entrada traducen a su protocolo (por ejemplo, a códigos HTTP)."""


class DatoInvalido(ValueError):
    """La petición no cumple una regla del negocio (HTTP 400)."""


class NoConfigurado(RuntimeError):
    """Falta configurar un servicio externo para poder hacerlo (HTTP 503)."""
