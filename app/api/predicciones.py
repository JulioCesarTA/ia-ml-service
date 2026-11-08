"""Los 3 modelos de IA del comedor, con datos reales en tiempo real:
  - Regresión (supervisado): raciones esperadas por plato, turno y día.
  - Clustering (no supervisado): agrupación de platos (mantener / ajustar / retirar).
  - Deep Learning (TensorFlow): porcentaje que se comió cada persona respecto a la porción de referencia."""
import time
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from app.models.predicciones import DemandaIn
from app.services.analitica import agrupamiento, clima, datos, kpis, regresion, vision
from app.services.reportes import fuentes

router = APIRouter()


# ----------------------------- supervisado: regresión -----------------------------
@router.post("/demanda")
def demanda(body: DemandaIn):
    out = regresion.predecir(body.fecha.isoformat(), body.plato_id, body.turno)
    return {"fecha": body.fecha, "platoId": body.plato_id, "turno": body.turno, **out}


@router.get("/regresion")
def regresion_estado():
    return regresion.estado()


# ----------------------------- ejecutar ahora (con o sin internet) -----------------------------
@router.post("/reentrenar")
def reentrenar_ahora():
    """Recalcula YA los tres tableros: vuelve a leer los datos, reentrena el modelo y reagrupa los platos.

    Con internet actualiza también el clima; sin internet usa el último clima guardado (o ninguno) y el resto
    funciona igual, porque los datos salen de los servicios del comedor, no de internet.
    """
    t0 = time.time()
    datos.invalidar()
    fuentes.invalidar()
    internet = clima.actualizar()
    est = regresion.reentrenar()
    grupos = agrupamiento.calcular()
    ind = kpis.calcular()
    return {"ok": True, "segundos": round(time.time() - t0, 1), "internet": internet,
            "clima": "actualizado desde internet" if internet else "sin internet: se usó el último clima guardado",
            "prediccion": {"registros": est.get("muestras"), "entrenado": bool(est.get("metricas")), "minimo": est.get("minimo")},
            "agrupacion": {"registros": grupos.get("registros"), "platos": grupos.get("platos"), "suficiente": grupos.get("suficiente")},
            "kpi": ind.get("registros")}


# ----------------------------- indicadores clave -----------------------------
@router.get("/kpis")
def indicadores():
    return kpis.calcular()


# ----------------------------- no supervisado: clustering de platos -----------------------------
@router.get("/agrupar-platos")
def agrupar_platos():
    return agrupamiento.calcular()


# ----------------------------- deep learning: foto de bandeja -----------------------------
@router.get("/vision/platos")
def vision_platos():
    """Platos de los menús de hoy (o del último día con menú) para elegir al subir la referencia."""
    filas = [x for x in datos.filas() if x["fecha"] <= date.today().isoformat()]
    ultimo = max((x["fecha"] for x in filas), default=None)
    return {"hoy": date.today().isoformat(), "fecha": ultimo,
            "platos": [{"platoId": x["platoId"], "turno": x["turno"], "fecha": x["fecha"]} for x in filas if x["fecha"] == ultimo]}


@router.post("/vision/referencia")
async def vision_referencia(file: UploadFile = File(...), plato_id: str = Form(...), fecha: str = Form(...), turno: str = Form(...)):
    try:
        return vision.registrar_referencia(await file.read(), plato_id, fecha, turno)
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer la imagen: {e}")


@router.get("/vision/referencias")
def vision_referencias():
    return vision.referencias()


@router.post("/vision/bandeja")
async def vision_bandeja(file: UploadFile = File(...), ref_id: str = Form(...)):
    try:
        return vision.analizar_bandeja(await file.read(), ref_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"No se pudo analizar la imagen: {e}")


@router.get("/vision/resumen")
def vision_resumen():
    return {**vision.resumen(), "modelo": vision.nombre_modelo()}


@router.get("/vision/foto/{carpeta}/{fid}")
def vision_foto(carpeta: str, fid: str):
    ruta = vision.ruta_foto(carpeta, fid)
    if not ruta:
        raise HTTPException(404, "Foto no encontrada")
    return FileResponse(ruta, media_type="image/jpeg")
