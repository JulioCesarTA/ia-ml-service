"""Desperdicio POR SECTOR de la bandeja: cuánto quedó del arroz, de la ensalada, de la guarnición, de la carne y del postre.

Una red neuronal pequeña (entrenada con fotos de bandejas etiquetadas a mano: herramientas/entrenar_sectores.py) mira el
descriptor de cada zona de la foto (CNN + color + saturación + textura) y dice qué comida es, o si es bandeja vacía.
  % que queda de un sector = zonas de esa comida en la bandeja / zonas de esa comida en la foto llena de referencia.
  % que queda de la bandeja = promedio de los sectores.
Solo numpy (los pesos llegan como datos): el celular hace exactamente la misma cuenta sin conexión.
"""
import numpy as np

from app.domain.analitica.vision import REJ

CLASES = ("fondo", "arroz", "ensalada", "guarnicion", "proteina", "postre")
SECTORES = CLASES[1:]
NOMBRES_POR_DEFECTO = {"arroz": "arroz", "ensalada": "ensalada", "guarnicion": "guarnición", "proteina": "carne", "postre": "postre"}
MIN_ZONAS_SECTOR = 40          # un sector "existe" en la foto llena si ocupa al menos ~1,3 % de la foto


def entrada(d: np.ndarray, sat: np.ndarray, tex: np.ndarray) -> np.ndarray:
    """Lo que mira la red por zona: descriptor CNN+color (147) + saturación + textura (x4, para que pese como el resto)."""
    return np.hstack([d, sat[:, None], 4.0 * tex[:, None]]).astype(np.float32)


def probabilidades(x: np.ndarray, modelo: dict) -> np.ndarray:
    """Promedio de las redes del modelo (capa oculta ReLU + softmax). [zonas, clases]"""
    z = (x - np.asarray(modelo["media"], np.float32)) / np.asarray(modelo["escala"], np.float32)
    total = np.zeros((len(x), len(modelo["clases"])), np.float64)
    for red in modelo["redes"]:
        h = np.maximum(0.0, z @ np.asarray(red["W1"], np.float32) + np.asarray(red["b1"], np.float32))
        o = h @ np.asarray(red["W2"], np.float32) + np.asarray(red["b2"], np.float32)
        o = np.exp(o - o.max(axis=1, keepdims=True))
        total += o / o.sum(axis=1, keepdims=True)
    return total / len(modelo["redes"])


def moda(pred: np.ndarray, k: int = len(CLASES)) -> np.ndarray:
    """Alisado: cada zona toma la clase más votada de su vecindario 3x3 (quita zonas sueltas)."""
    oh = np.eye(k, dtype=np.float32)[pred].reshape(REJ, REJ, k)
    p = np.pad(oh, ((1, 1), (1, 1), (0, 0)), mode="edge")
    votos = sum(p[i:i + REJ, j:j + REJ] for i in range(3) for j in range(3))
    return votos.argmax(axis=2).ravel()


def clasificar_zonas(x: np.ndarray, modelo: dict) -> np.ndarray:
    """Clase de cada zona (índice en CLASES)."""
    p = probabilidades(x, modelo)
    p[:, 0] *= float(modelo.get("sesgo_fondo", 1.0))       # ante la duda, bandeja vacía
    return moda(p.argmax(axis=1))


def conteo(pred: np.ndarray) -> dict[str, int]:
    return {c: int((pred == k).sum()) for k, c in enumerate(CLASES) if k > 0}


def sectores_referencia(pred: np.ndarray) -> dict[str, int]:
    """Sectores que tiene el plato lleno y cuántas zonas ocupa cada uno."""
    return {c: n for c, n in conteo(pred).items() if n >= MIN_ZONAS_SECTOR}


def nombres_validos(nombres: dict | None, base: dict | None = None) -> dict[str, str]:
    """Nombre a mostrar de cada sector (p. ej. proteina -> «pollo»). Lo que no venga queda con el nombre del modelo
    (`base`, el plato con que se entrenó) o el genérico."""
    salida = {**NOMBRES_POR_DEFECTO, **{c: n for c, n in (base or {}).items() if c in SECTORES and isinstance(n, str)}}
    for c, n in (nombres or {}).items():
        if c in SECTORES and isinstance(n, str) and 0 < len(n.strip()) <= 40:
            salida[c] = n.strip()
    return salida


def comparar(zonas_ref: dict[str, int], pred_bandeja: np.ndarray, nombres: dict[str, str]) -> tuple[list[dict], float]:
    """([{clase, nombre, restante}], promedio). Solo los sectores que existían en la foto llena."""
    ahora = conteo(pred_bandeja)
    sectores = [{"clase": c, "nombre": nombres.get(c, c), "restante": round(min(100.0, 100.0 * ahora.get(c, 0) / n), 1)}
                for c, n in zonas_ref.items() if n > 0]
    promedio = round(float(np.mean([s["restante"] for s in sectores])), 1) if sectores else 0.0
    return sectores, promedio


def sectores_ref_validos(v) -> dict | None:
    """Sectores de una foto llena hecha en el celular: {"zonas": {clase: n}, "nombres": {clase: nombre}}."""
    if v is None:
        return None
    zonas = v.get("zonas") if isinstance(v, dict) else None
    if not isinstance(zonas, dict) or not all(c in SECTORES and isinstance(n, int) and 0 < n <= REJ * REJ for c, n in zonas.items()):
        raise ValueError("«sectores.zonas» debe ser {sector: zonas (entero)} con sectores conocidos")
    return {"zonas": dict(zonas), "nombres": nombres_validos(v.get("nombres"))}


def sectores_validos(v) -> list[dict] | None:
    """Sectores que manda el celular: [{clase, nombre, restante 0-100}]."""
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > len(SECTORES):
        raise ValueError("«sectores» debe ser una lista de hasta 5 sectores")
    salida = []
    for s in v:
        c, r = s.get("clase") if isinstance(s, dict) else None, s.get("restante", -1) if isinstance(s, dict) else -1
        if c not in SECTORES or not isinstance(r, (int, float)) or not 0 <= r <= 100:
            raise ValueError("cada sector necesita «clase» válida y «restante» entre 0 y 100")
        salida.append({"clase": c, "nombre": nombres_validos({c: s.get("nombre")})[c], "restante": round(float(r), 1)})
    return salida
