"""Deep Learning (TensorFlow) + lectura de imágenes (Pillow): puerto ProcesadorImagenes.

Una red convolucional (MobileNetV2, TensorFlow) convierte la foto en un mapa de 56x56 zonas, cada una descrita por
144 características más su color. Los pesos van incluidos en la imagen del servicio: funciona sin internet.
"""
import io

import numpy as np
from PIL import Image

from app.domain.analitica.vision import CAPA, LADO, PESO_COLOR, REJ

_modelo = {"m": None, "nombre": ""}


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


class ProcesadorTensorFlow:
    def nombre_modelo(self) -> str:
        _cnn()
        return _modelo["nombre"]

    def cargar(self, datos: bytes) -> Image.Image:
        return Image.open(io.BytesIO(datos)).convert("RGB")

    def zonas(self, imagen: Image.Image) -> tuple[np.ndarray, np.ndarray]:
        """(descriptor de cada zona [3136, 144+3], 'aspecto de comida' de cada zona [3136])."""
        pq = imagen.resize((LADO, LADO))
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

    def jpeg_reducido(self, imagen: Image.Image) -> bytes:
        chica = imagen.copy()
        chica.thumbnail((900, 900))
        buf = io.BytesIO()
        chica.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
