"""Reportes del comedor: el motor y el intérprete de español viven AQUÍ (una sola implementación para todos los clientes).

- POST /reportes/consulta : texto en español -> tabla, gráfico y resumen (lo usan el portal, el BI y la app móvil)
- GET  /reportes/snapshot : copia de los datos del rol (la app móvil la guarda para trabajar sin conexión)
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.services.reportes import catalogo, lenguaje, motor, snapshot

router = APIRouter()


def _roles(rol: str, x_roles: str | None) -> list[str]:
    return [r.strip() for r in (x_roles or rol).split(",") if r.strip()]


class ConsultaIn(BaseModel):
    texto: str
    previa: dict | None = None      # la consulta anterior, para seguir la conversación («ahora por mes»)
    rol: str = "administrador"


@router.get("/catalogo")
def get_catalogo(rol: str = "administrador", x_roles: str | None = Header(default=None)):
    """Qué puede pedir este rol: conjuntos, columnas y ejemplos (para la ayuda de las pantallas)."""
    permitidos = snapshot.permitidos(_roles(rol, x_roles))
    return {"datasets": [
        {"id": did, "etiqueta": d["etiqueta"], "descripcion": d["descripcion"],
         "columnas": [{"nombre": c["nombre"], "etiqueta": c["etiqueta"], "tipo": c["tipo"], "fmt": c["fmt"]} for c in d["columnas"]],
         "ejemplos": d["ejemplos"]}
        for did, d in catalogo.DATASETS.items() if did in permitidos]}


@router.post("/consulta")
def consulta(body: ConsultaIn, x_roles: str | None = Header(default=None)):
    """Pedido en español -> reporte. Nunca arma SQL: el texto solo rellena una consulta validada contra el catálogo."""
    roles = _roles(body.rol, x_roles)
    datos, errores = snapshot.registros(roles)
    if not datos:
        raise HTTPException(503, "No pude leer los datos del comedor ahora mismo: " + "; ".join(errores.values()) or "sin datos")
    try:
        leido = lenguaje.interpretar(body.texto, previa=body.previa, registros=datos)
        reporte = motor.ejecutar(leido["spec"], datos)
    except lenguaje.NoEntendido as e:
        raise HTTPException(422, str(e))
    except motor.ConsultaInvalida as e:
        raise HTTPException(400, str(e))
    return {**reporte, "spec": leido["spec"], "entendi": leido["entendi"],
            "notas": reporte["notas"] + leido["notas"], "confianza": leido["confianza"],
            "continuacion": leido["continuacion"], "fuentesConError": errores}


class EjecutarIn(BaseModel):
    spec: dict
    rol: str = "administrador"


@router.post("/ejecutar")
def ejecutar(body: EjecutarIn, x_roles: str | None = Header(default=None)):
    """Vuelve a ejecutar una consulta ya armada (los botones «agrupar por mes», «primeros 10», etc.)."""
    datos, errores = snapshot.registros(_roles(body.rol, x_roles))
    try:
        return {**motor.ejecutar(body.spec, datos), "spec": body.spec, "fuentesConError": errores}
    except motor.ConsultaInvalida as e:
        raise HTTPException(400, str(e))


@router.get("/snapshot")
def get_snapshot(rol: str = "administrador", x_roles: str | None = Header(default=None)):
    """Copia de los datos permitidos para el rol. Con la autenticación activa, el gateway fija x-roles desde el token."""
    return snapshot.construir(_roles(rol, x_roles))
