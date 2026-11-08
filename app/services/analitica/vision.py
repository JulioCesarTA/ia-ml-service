"""Deep Learning (TensorFlow): cuánto de la comida se comió cada persona, comparando con la porción real.

Flujo:
  1) Se sube UNA foto de referencia de cómo se ve la porción completa de un plato (por plato, día y turno).
  2) Cada bandeja de un comensal se compara con esa referencia y se estima qué % de la comida quedó y cuánto se comió.

Cómo funciona (una sola foto de referencia, sin etiquetas de desperdicio):
  - Una red convolucional (MobileNetV2, TensorFlow) convierte la foto en un mapa de 56x56 zonas, cada una descrita por
    144 características más su color. Los pesos van incluidos en la imagen del servicio: funciona sin internet.
  - En la referencia se separan las zonas de COMIDA (más color y textura) de las de plato/bandeja y se guardan varios
    "aspectos" típicos de cada tipo (prototipos).
  - En cada bandeja, cada zona se clasifica por su parecido con esos prototipos (y se alisa el resultado); el área de
    comida que queda, dividida entre la de la referencia, da el % restante.
Es una estimación por área visible: funciona mejor con fotos tomadas desde arriba, con la misma cámara y buena luz.
"""
import io
import os
import re
import uuid

import numpy as np
from PIL import Image

from app.data import repo_vision, s3_fotos

REJ = 56                       # zonas por lado (mapa 56x56)
LADO = 224
CAPA = "block_3_expand_relu"   # 56x56x144: características locales (borde, color, textura)
PESO_COLOR = 0.9
_modelo = {"m": None, "nombre": ""}


def _dir() -> str:
    return repo_vision.directorio_fotos()


def _cnn():
    if _modelo["m"] is None:
        import tensorflow as tf
        try:
            base = tf.keras.applications.MobileNetV2(weights="imagenet", include_top=False, input_shape=(LADO, LADO, 3))
            _modelo["nombre"] = "MobileNetV2 con pesos ImageNet (TensorFlow)"
        except Exception:                            # sin pesos locales y sin internet: red con pesos fijos (semilla)
            tf.keras.utils.set_random_seed(7)
            base = tf.keras.applications.MobileNetV2(weights=None, include_top=False, input_shape=(LADO, LADO, 3))
            _modelo["nombre"] = "MobileNetV2 sin preentrenar (TensorFlow)"
        _modelo["m"] = tf.keras.Model(base.input, base.get_layer(CAPA).output)
    return _modelo["m"]


def nombre_modelo() -> str:
    _cnn()
    return _modelo["nombre"]


def _cargar(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _alisar(mascara: np.ndarray) -> np.ndarray:
    """Quita zonas sueltas: una zona es comida si la mayoría de su vecindario 3x3 lo es."""
    m = mascara.reshape(REJ, REJ).astype(np.float32)
    p = np.pad(m, 1, mode="edge")
    vecinos = sum(p[i:i + REJ, j:j + REJ] for i in range(3) for j in range(3))
    return (vecinos >= 5).ravel()


def _zonas(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """(descriptor de cada zona [3136, 144+3], 'aspecto de comida' de cada zona [3136])."""
    pq = img.resize((LADO, LADO))
    arr = np.asarray(pq, dtype=np.float32)
    f = _cnn().predict((arr / 127.5 - 1.0)[None], verbose=0)[0].reshape(REJ * REJ, -1)
    f = f / (np.linalg.norm(f, axis=1, keepdims=True) + 1e-8)
    paso = LADO // REJ
    rgb = (arr / 255.0).reshape(REJ, paso, REJ, paso, 3).mean(axis=(1, 3)).reshape(REJ * REJ, 3)
    sat_px = np.asarray(pq.convert("HSV"), dtype=np.float32)[..., 1] / 255.0
    gris = np.asarray(pq.convert("L"), dtype=np.float32) / 255.0
    sat = sat_px.reshape(REJ, paso, REJ, paso).mean(axis=(1, 3)).ravel()
    tex = gris.reshape(REJ, paso, REJ, paso).std(axis=(1, 3)).ravel()
    norm = lambda v: v / (v.max() + 1e-8)
    return np.hstack([f, PESO_COLOR * rgb]), norm(sat) + norm(tex)


def _otsu(v: np.ndarray) -> tuple[float, float]:
    """Umbral que separa 'comida' (más color y textura) de plato/bandeja, y qué tan clara es la separación (0-1)."""
    mejor, umbral, total = -1.0, float(np.median(v)), float(v.var()) + 1e-12
    for t in np.linspace(v.min(), v.max(), 64)[1:-1]:
        a, b = v[v <= t], v[v > t]
        if len(a) < 5 or len(b) < 5:
            continue
        w = len(a) * len(b) / len(v) ** 2 * (a.mean() - b.mean()) ** 2
        if w > mejor:
            mejor, umbral = w, float(t)
    return umbral, max(0.0, mejor) / total


def _guardar_foto(carpeta: str, fid: str, img: Image.Image, fecha_iso: str | None = None) -> str | None:
    """Guarda la foto en el disco y, si S3 está configurado, también allá. Devuelve la clave en S3 (o None)."""
    os.makedirs(os.path.join(_dir(), carpeta), exist_ok=True)
    chica = img.copy()
    chica.thumbnail((900, 900))
    chica.save(os.path.join(_dir(), carpeta, f"{fid}.jpg"), quality=85)
    clave = s3_fotos.clave_foto(carpeta, fid, fecha_iso)
    buf = io.BytesIO()
    chica.save(buf, format="JPEG", quality=85)
    return clave if s3_fotos.subir(clave, buf.getvalue()) else None


def ruta_foto(carpeta: str, fid: str) -> str | None:
    if carpeta not in ("ref", "bandeja") or not fid.isalnum():
        return None
    p = os.path.join(_dir(), carpeta, f"{fid}.jpg")
    return p if os.path.exists(p) else None


# ----------------------------- referencia -----------------------------

def _prototipos(d: np.ndarray, k: int) -> np.ndarray:
    from sklearn.cluster import KMeans
    k = max(1, min(k, len(d)))
    return KMeans(n_clusters=k, n_init=5, random_state=0).fit(d).cluster_centers_


def _clasificar(d: np.ndarray, comida: np.ndarray, fondo: np.ndarray) -> tuple[np.ndarray, float]:
    """Cada zona es comida si su prototipo más parecido es de comida. Devuelve (máscara, confianza 0-1)."""
    dist = lambda protos: np.min(np.linalg.norm(d[:, None, :] - protos[None], axis=2), axis=1)
    dc, dg = dist(comida), dist(fondo)
    return dc < dg, float(np.mean(np.abs(dg - dc) / (dg + dc + 1e-8)))


def registrar_referencia(data: bytes, plato_id: str, fecha: str, turno: str) -> dict:
    img = _cargar(data)
    d, aspecto = _zonas(img)
    umbral, claridad = _otsu(aspecto)
    comida = _alisar(aspecto > umbral)
    adv = None
    if claridad < 0.35:
        adv = "Hay poco contraste entre la comida y el plato: toma la foto desde arriba, con buena luz y la bandeja completa."
    if comida.sum() < 8 or comida.mean() > 0.9:
        adv = "No se distingue bien la comida en la foto de referencia: vuelve a tomarla más cerca y con mejor luz."
    if comida.sum() < 8 or (~comida).sum() < 8:
        raise ValueError(adv)
    p_comida, p_fondo = _prototipos(d[comida], 4), _prototipos(d[~comida], 4)
    comida, _ = _clasificar(d, p_comida, p_fondo)                 # misma regla que se usará con las bandejas
    comida = _alisar(comida)
    f_ref = float(comida.mean())
    rid = uuid.uuid4().hex[:10]
    np.savez(os.path.join(_dir(), f"{rid}.npz"), comida=p_comida, fondo=p_fondo)
    foto_key = _guardar_foto("ref", rid, img, fecha)
    repo_vision.guardar_referencia(rid, plato_id, fecha, turno, f_ref, adv, foto_key=foto_key)
    return {"id": rid, "platoId": plato_id, "fecha": fecha, "turno": turno, "zonasComida": int(comida.sum()),
            "fraccionComida": round(f_ref, 3), "advertencia": adv, "mascara": comida.reshape(REJ, REJ).astype(int).tolist(),
            "modelo": nombre_modelo()}


def referencias(limite: int = 30) -> list[dict]:
    return repo_vision.referencias(limite)


# ----------------------------- bandejas -----------------------------

def analizar_bandeja(data: bytes, ref_id: str) -> dict:
    r = repo_vision.referencia(ref_id)
    if r is None:
        raise ValueError("La referencia no existe")
    p = np.load(os.path.join(_dir(), f"{ref_id}.npz"))
    img = _cargar(data)
    d, _ = _zonas(img)
    es_comida, confianza = _clasificar(d, p["comida"], p["fondo"])
    es_comida = _alisar(es_comida)
    restante = float(min(100.0, 100.0 * es_comida.mean() / r["f_ref"])) if r["f_ref"] > 0 else 0.0
    bid = uuid.uuid4().hex[:10]
    foto_key = _guardar_foto("bandeja", bid, img, r["fecha"])
    repo_vision.guardar_bandeja(bid, ref_id, r["plato_id"], r["fecha"], r["turno"],
                                round(restante, 1), round(100 - restante, 1), round(confianza, 2), foto_key=foto_key)
    return {"id": bid, "refId": ref_id, "platoId": r["plato_id"], "restantePct": round(restante, 1), "comidoPct": round(100 - restante, 1),
            "confianza": round(confianza, 2), "mascara": es_comida.reshape(REJ, REJ).astype(int).tolist()}


def resumen() -> dict:
    r = repo_vision.resumen_bandejas()
    return {"referencias": len(referencias(1000)), "bandejas": r["bandejas"],
            "restanteMedio": None if r["restanteMedio"] is None else round(r["restanteMedio"], 1),
            "porPlato": r["porPlato"], "porDia": r["porDia"], "recientes": r["recientes"]}


def desperdicio_medio_por_plato() -> dict[str, float]:
    return repo_vision.restante_medio_por_plato(3)


# ----------------------------- celular: IA local + fotos en S3 -----------------------------
# El celular analiza la bandeja sin internet con su propia copia de la CNN (TensorFlow Lite) y las referencias que descargó.
# Cuando hay red sube la foto directo a S3 (URL temporal) y manda aquí solo el resultado y la clave de la foto.

DIM = 147                                           # 144 características de la CNN + 3 de color
TURNOS_VALIDOS = ("DESAYUNO", "ALMUERZO", "CENA")
_ID_CLIENTE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def _validar_id_cliente(cid: str) -> str:
    if not isinstance(cid, str) or not _ID_CLIENTE.match(cid):
        raise ValueError("cliente_id inválido (8-64 letras, números o guiones)")
    return cid


def paquete_movil(limite: int = 60) -> dict:
    """Referencias (prototipos de comida y de plato) para que el celular analice bandejas sin conexión."""
    refs = []
    for r in repo_vision.referencias(limite):
        ruta = os.path.join(_dir(), f"{r['id']}.npz")
        if not os.path.exists(ruta):
            continue
        p = np.load(ruta)
        refs.append({"id": r["id"], "platoId": r["plato_id"], "fecha": r["fecha"], "turno": r["turno"], "fRef": round(r["f_ref"], 4),
                     "comida": np.round(p["comida"], 4).tolist(), "fondo": np.round(p["fondo"], 4).tolist()})
    return {"dim": DIM, "rejilla": REJ, "lado": LADO, "capa": CAPA, "pesoColor": PESO_COLOR, "referencias": refs}


def _prototipos_validos(v, nombre: str) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != DIM or not 1 <= a.shape[0] <= 8 or not np.isfinite(a).all():
        raise ValueError(f"«{nombre}» debe ser una lista de 1 a 8 vectores de {DIM} números")
    return a.astype(np.float32)


def url_subida(tipo: str, cliente_id: str, fecha_iso: str | None = None) -> dict:
    if tipo not in ("ref", "bandeja"):
        raise ValueError("tipo debe ser «ref» o «bandeja»")
    clave = s3_fotos.clave_foto(tipo, _validar_id_cliente(cliente_id), fecha_iso)
    return {"clave": clave, "url": s3_fotos.url_subida(clave), "metodo": "PUT",
            "encabezados": {"Content-Type": "image/jpeg", "x-amz-server-side-encryption": "AES256"}, "expira": 600}


def _clave_confirmada(clave, carpeta: str) -> str | None:
    """Acepta la clave de S3 solo si es del tipo esperado y el objeto realmente existe."""
    if not clave or not isinstance(clave, str) or not clave.startswith("referencias/" if carpeta == "ref" else "bandejas/"):
        return None
    return clave if s3_fotos.existe(clave) else None


def registrar_referencia_movil(p: dict) -> dict:
    cid = _validar_id_cliente(p.get("cliente_id"))
    previo = repo_vision.por_cliente("ref_porcion", cid)
    if previo:                                       # ya llegó (reintento): se devuelve lo guardado, no se duplica
        return {"id": previo["id"], "repetido": True}
    if p.get("turno") not in TURNOS_VALIDOS:
        raise ValueError("turno inválido")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(p.get("fecha", ""))):
        raise ValueError("fecha inválida (AAAA-MM-DD)")
    plato = str(p.get("plato_id", "")).strip()
    if not plato or len(plato) > 80:
        raise ValueError("plato_id inválido")
    f_ref = float(p.get("f_ref", 0))
    if not 0 < f_ref <= 1:
        raise ValueError("f_ref debe estar entre 0 y 1")
    comida, fondo = _prototipos_validos(p.get("comida"), "comida"), _prototipos_validos(p.get("fondo"), "fondo")
    rid = uuid.uuid4().hex[:10]
    np.savez(os.path.join(_dir(), f"{rid}.npz"), comida=comida, fondo=fondo)
    repo_vision.guardar_referencia(rid, plato, p["fecha"], p["turno"], f_ref, p.get("advertencia"),
                                   foto_key=_clave_confirmada(p.get("foto_key"), "ref"), origen="movil", cliente_id=cid)
    return {"id": rid, "repetido": False}


def registrar_bandeja_movil(p: dict) -> dict:
    cid = _validar_id_cliente(p.get("cliente_id"))
    previo = repo_vision.por_cliente("bandejas", cid)
    if previo:
        return {"id": previo["id"], "repetido": True}
    r = repo_vision.referencia(str(p.get("ref_id", "")))
    if r is None:
        raise LookupError("La referencia no existe en el servidor (¿aún no se sincronizó?)")
    restante, confianza = float(p.get("restante", -1)), float(p.get("confianza", -1))
    if not (0 <= restante <= 100) or not (0 <= confianza <= 1):
        raise ValueError("restante debe estar entre 0 y 100 y confianza entre 0 y 1")
    bid = uuid.uuid4().hex[:10]
    repo_vision.guardar_bandeja(bid, r["id"], r["plato_id"], r["fecha"], r["turno"], round(restante, 1), round(100 - restante, 1),
                                round(confianza, 2), foto_key=_clave_confirmada(p.get("foto_key"), "bandeja"), origen="movil", cliente_id=cid)
    return {"id": bid, "repetido": False}


def url_foto(carpeta: str, fid: str) -> str | None:
    """URL temporal de la foto en S3 si existe allá (las fotos nuevas viven en S3)."""
    clave = repo_vision.foto_key(carpeta, fid) if carpeta in ("ref", "bandeja") and fid.isalnum() else None
    return s3_fotos.url_lectura(clave) if clave else None
