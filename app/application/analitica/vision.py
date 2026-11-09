"""Deep Learning: cuánto de la comida se comió cada persona, comparando con la porción real (caso de uso).

Flujo:
  1) Se sube UNA foto de referencia de cómo se ve la porción completa de un plato (por plato, día y turno).
  2) Cada bandeja de un comensal se compara con esa referencia y se estima qué % de la comida quedó y cuánto se comió.

La CNN (puerto ProcesadorImagenes) describe cada zona; las reglas de separación y comparación están en el dominio.
Es una estimación por área visible: funciona mejor con fotos tomadas desde arriba, con la misma cámara y buena luz.
"""
import uuid

import numpy as np

from app.application.ports.externos import AlmacenObjetos, ArchivosVision, ProcesadorImagenes
from app.application.ports.repositorios import RepositorioVision
from app.domain import fotos
from app.domain.analitica import vision as dom
from app.domain.analitica.vision import CAPA, DIM, LADO, PESO_COLOR, REJ


class ServicioVision:
    DIM = DIM

    def __init__(self, repo: RepositorioVision, archivos: ArchivosVision, objetos: AlmacenObjetos,
                 procesador: ProcesadorImagenes):
        self._repo = repo
        self._archivos = archivos
        self._s3 = objetos
        self._cnn = procesador

    def nombre_modelo(self) -> str:
        return self._cnn.nombre_modelo()

    def _guardar_foto(self, carpeta: str, fid: str, img, fecha_iso: str | None = None) -> str | None:
        """Guarda la foto en el disco y, si S3 está configurado, también allá. Devuelve la clave en S3 (o None)."""
        jpeg = self._cnn.jpeg_reducido(img)
        self._archivos.guardar_foto(carpeta, fid, jpeg)
        clave = fotos.clave_foto(carpeta, fid, fecha_iso)
        return clave if self._s3.subir(clave, jpeg) else None

    def ruta_foto(self, carpeta: str, fid: str) -> str | None:
        if not dom.carpeta_valida(carpeta, fid):
            return None
        return self._archivos.ruta_foto(carpeta, fid)

    # ----------------------------- referencia -----------------------------

    def registrar_referencia(self, data: bytes, plato_id: str, fecha: str, turno: str) -> dict:
        img = self._cnn.cargar(data)
        d, aspecto = self._cnn.zonas(img)
        ref = dom.analizar_referencia(d, aspecto)
        rid = uuid.uuid4().hex[:10]
        self._archivos.guardar_prototipos(rid, ref["p_comida"], ref["p_fondo"])
        foto_key = self._guardar_foto("ref", rid, img, fecha)
        self._repo.guardar_referencia(rid, plato_id, fecha, turno, ref["f_ref"], ref["advertencia"], foto_key=foto_key)
        comida = ref["comida"]
        return {"id": rid, "platoId": plato_id, "fecha": fecha, "turno": turno, "zonasComida": int(comida.sum()),
                "fraccionComida": round(ref["f_ref"], 3), "advertencia": ref["advertencia"], "mascara": dom.mascara_lista(comida),
                "modelo": self.nombre_modelo()}

    def referencias(self, limite: int = 30) -> list[dict]:
        return self._repo.referencias(limite)

    # ----------------------------- bandejas -----------------------------

    def analizar_bandeja(self, data: bytes, ref_id: str) -> dict:
        r = self._repo.referencia(ref_id)
        if r is None:
            raise ValueError("La referencia no existe")
        p = self._archivos.cargar_prototipos(ref_id)
        img = self._cnn.cargar(data)
        d, _ = self._cnn.zonas(img)
        es_comida, restante, confianza = dom.analizar_bandeja(d, p["comida"], p["fondo"], r["f_ref"])
        bid = uuid.uuid4().hex[:10]
        foto_key = self._guardar_foto("bandeja", bid, img, r["fecha"])
        self._repo.guardar_bandeja(bid, ref_id, r["plato_id"], r["fecha"], r["turno"],
                                   round(restante, 1), round(100 - restante, 1), round(confianza, 2), foto_key=foto_key)
        return {"id": bid, "refId": ref_id, "platoId": r["plato_id"], "restantePct": round(restante, 1), "comidoPct": round(100 - restante, 1),
                "confianza": round(confianza, 2), "mascara": dom.mascara_lista(es_comida)}

    def resumen(self) -> dict:
        r = self._repo.resumen_bandejas()
        return {"referencias": len(self.referencias(1000)), "bandejas": r["bandejas"],
                "restanteMedio": None if r["restanteMedio"] is None else round(r["restanteMedio"], 1),
                "porPlato": r["porPlato"], "porDia": r["porDia"], "recientes": r["recientes"]}

    def desperdicio_medio_por_plato(self) -> dict[str, float]:
        return self._repo.restante_medio_por_plato(3)

    # ----------------------------- celular: IA local + fotos en S3 -----------------------------
    # El celular analiza la bandeja sin internet con su propia copia de la CNN (TensorFlow Lite) y las referencias que descargó.
    # Cuando hay red sube la foto directo a S3 (URL temporal) y manda aquí solo el resultado y la clave de la foto.

    def paquete_movil(self, limite: int = 60) -> dict:
        """Referencias (prototipos de comida y de plato) para que el celular analice bandejas sin conexión."""
        refs = []
        for r in self._repo.referencias(limite):
            if not self._archivos.hay_prototipos(r["id"]):
                continue
            p = self._archivos.cargar_prototipos(r["id"])
            refs.append({"id": r["id"], "platoId": r["plato_id"], "fecha": r["fecha"], "turno": r["turno"], "fRef": round(r["f_ref"], 4),
                         "comida": np.round(p["comida"], 4).tolist(), "fondo": np.round(p["fondo"], 4).tolist()})
        return {"dim": DIM, "rejilla": REJ, "lado": LADO, "capa": CAPA, "pesoColor": PESO_COLOR, "referencias": refs}

    def url_subida(self, tipo: str, cliente_id: str, fecha_iso: str | None = None) -> dict:
        if tipo not in ("ref", "bandeja"):
            raise ValueError("tipo debe ser «ref» o «bandeja»")
        clave = fotos.clave_foto(tipo, dom.validar_id_cliente(cliente_id), fecha_iso)
        return {"clave": clave, "url": self._s3.url_subida(clave), "metodo": "PUT",
                "encabezados": {"Content-Type": "image/jpeg", "x-amz-server-side-encryption": "AES256"}, "expira": 600}

    def _clave_confirmada(self, clave, carpeta: str) -> str | None:
        """Acepta la clave de S3 solo si es del tipo esperado y el objeto realmente existe."""
        if not clave or not isinstance(clave, str) or not clave.startswith("referencias/" if carpeta == "ref" else "bandejas/"):
            return None
        return clave if self._s3.existe(clave) else None

    def registrar_referencia_movil(self, p: dict) -> dict:
        cid = dom.validar_id_cliente(p.get("cliente_id"))
        previo = self._repo.por_cliente("ref_porcion", cid)
        if previo:                                       # ya llegó (reintento): se devuelve lo guardado, no se duplica
            return {"id": previo["id"], "repetido": True}
        plato, f_ref = dom.validar_referencia_movil(p)
        comida, fondo = dom.prototipos_validos(p.get("comida"), "comida"), dom.prototipos_validos(p.get("fondo"), "fondo")
        rid = uuid.uuid4().hex[:10]
        self._archivos.guardar_prototipos(rid, comida, fondo)
        self._repo.guardar_referencia(rid, plato, p["fecha"], p["turno"], f_ref, p.get("advertencia"),
                                      foto_key=self._clave_confirmada(p.get("foto_key"), "ref"), origen="movil", cliente_id=cid)
        return {"id": rid, "repetido": False}

    def registrar_bandeja_movil(self, p: dict) -> dict:
        cid = dom.validar_id_cliente(p.get("cliente_id"))
        previo = self._repo.por_cliente("bandejas", cid)
        if previo:
            return {"id": previo["id"], "repetido": True}
        r = self._repo.referencia(str(p.get("ref_id", "")))
        if r is None:
            raise LookupError("La referencia no existe en el servidor (¿aún no se sincronizó?)")
        restante, confianza = dom.validar_bandeja_movil(p)
        bid = uuid.uuid4().hex[:10]
        self._repo.guardar_bandeja(bid, r["id"], r["plato_id"], r["fecha"], r["turno"], round(restante, 1), round(100 - restante, 1),
                                   round(confianza, 2), foto_key=self._clave_confirmada(p.get("foto_key"), "bandeja"), origen="movil", cliente_id=cid)
        return {"id": bid, "repetido": False}

    def url_foto(self, carpeta: str, fid: str) -> str | None:
        """URL temporal de la foto en S3 si existe allá (las fotos nuevas viven en S3)."""
        clave = self._repo.foto_key(carpeta, fid) if dom.carpeta_valida(carpeta, fid) else None
        return self._s3.url_lectura(clave) if clave else None
