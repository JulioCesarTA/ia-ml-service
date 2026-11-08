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
import uuid

import numpy as np
from PIL import Image

from app.data import repo_vision

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


def _guardar_foto(carpeta: str, fid: str, img: Image.Image) -> None:
    os.makedirs(os.path.join(_dir(), carpeta), exist_ok=True)
    chica = img.copy()
    chica.thumbnail((900, 900))
    chica.save(os.path.join(_dir(), carpeta, f"{fid}.jpg"), quality=85)


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
    _guardar_foto("ref", rid, img)
    repo_vision.guardar_referencia(rid, plato_id, fecha, turno, f_ref, adv)
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
    _guardar_foto("bandeja", bid, img)
    repo_vision.guardar_bandeja(bid, ref_id, r["plato_id"], r["fecha"], r["turno"],
                                round(restante, 1), round(100 - restante, 1), round(confianza, 2))
    return {"id": bid, "refId": ref_id, "platoId": r["plato_id"], "restantePct": round(restante, 1), "comidoPct": round(100 - restante, 1),
            "confianza": round(confianza, 2), "mascara": es_comida.reshape(REJ, REJ).astype(int).tolist()}


def resumen() -> dict:
    r = repo_vision.resumen_bandejas()
    return {"referencias": len(referencias(1000)), "bandejas": r["bandejas"],
            "restanteMedio": None if r["restanteMedio"] is None else round(r["restanteMedio"], 1),
            "porPlato": r["porPlato"], "porDia": r["porDia"], "recientes": r["recientes"]}


def desperdicio_medio_por_plato() -> dict[str, float]:
    return repo_vision.restante_medio_por_plato(3)
