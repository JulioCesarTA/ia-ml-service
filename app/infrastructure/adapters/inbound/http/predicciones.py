"""Los 3 modelos de IA del comedor, con datos reales en tiempo real:
  - Regresión (supervisado): raciones esperadas por plato, turno y día.
  - Clustering (no supervisado): agrupación de platos (mantener / ajustar / retirar).
  - Deep Learning (TensorFlow): porcentaje que se comió cada persona respecto a la porción de referencia."""
import json
import time
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.application.analitica.agrupamiento import ServicioAgrupamiento
from app.application.analitica.clima import ServicioClima
from app.application.analitica.datos import DatosMenus
from app.application.analitica.kpis import ServicioKpis
from app.application.analitica.regresion import ServicioRegresion
from app.application.analitica.vision import ServicioVision
from app.application.reportes.fuentes import FuentesReportes
from app.infrastructure.adapters.inbound.http.esquemas.predicciones import BandejaMovilIn, DemandaIn, ReferenciaMovilIn, SubidaIn


def _movil(fn, datos):
    try:
        return fn(datos)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


def crear_router(regresion: ServicioRegresion, datos: DatosMenus, fuentes: FuentesReportes, clima: ServicioClima,
                 agrupamiento: ServicioAgrupamiento, kpis: ServicioKpis, vision: ServicioVision) -> APIRouter:
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
    async def vision_referencia(file: UploadFile = File(...), plato_id: str = Form(...), fecha: str = Form(...), turno: str = Form(...),
                                nombres: str | None = Form(None)):
        """`nombres` (opcional, JSON): cómo se llama cada sector en este plato, p. ej. {"proteina": "pollo", "postre": "naranja"}."""
        try:
            n = json.loads(nombres) if nombres else None
            return vision.registrar_referencia(await file.read(), plato_id, fecha, turno, n if isinstance(n, dict) else None)
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
        if ruta:
            return FileResponse(ruta, media_type="image/jpeg")
        url = vision.url_foto(carpeta, fid)                  # ya no está en el disco: se sirve desde S3
        if url:
            return RedirectResponse(url, status_code=307)
        raise HTTPException(404, "Foto no encontrada")

    # ----------------------------- celular: IA local (TensorFlow Lite) + fotos en S3 -----------------------------
    @router.get("/vision/paquete-movil")
    def vision_paquete_movil(limite: int = 60):
        """Referencias para analizar bandejas en el celular sin conexión."""
        return vision.paquete_movil(min(max(limite, 1), 200))

    @router.post("/vision/subida")
    def vision_subida(body: SubidaIn):
        """URL temporal para que el celular suba la foto directo a S3."""
        try:
            return vision.url_subida(body.tipo, body.cliente_id, body.fecha)
        except RuntimeError as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.post("/vision/referencia-movil")
    def vision_referencia_movil(body: ReferenciaMovilIn):
        return _movil(vision.registrar_referencia_movil, body.model_dump())

    @router.post("/vision/bandeja-movil")
    def vision_bandeja_movil(body: BandejaMovilIn):
        return _movil(vision.registrar_bandeja_movil, body.model_dump())

    return router
