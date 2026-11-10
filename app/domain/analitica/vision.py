"""Reglas puras del análisis de bandejas: separar comida de plato/bandeja y comparar con la referencia (solo numpy).

La red convolucional que describe cada zona de la foto vive fuera del dominio (adaptador TensorFlow); aquí solo se
trabaja con los descriptores que entrega.
"""
import re

import numpy as np

REJ = 56                       # zonas por lado (mapa 56x56)
LADO = 224
CAPA = "block_3_expand_relu"   # 56x56x144: características locales (borde, color, textura)
PESO_COLOR = 0.9
DIM = 147                      # 144 características de la CNN + 3 de color
TURNOS_VALIDOS = ("DESAYUNO", "ALMUERZO", "CENA")
_ID_CLIENTE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def alisar(mascara: np.ndarray) -> np.ndarray:
    """Quita zonas sueltas: una zona es comida si la mayoría de su vecindario 3x3 lo es."""
    m = mascara.reshape(REJ, REJ).astype(np.float32)
    p = np.pad(m, 1, mode="edge")
    vecinos = sum(p[i:i + REJ, j:j + REJ] for i in range(3) for j in range(3))
    return (vecinos >= 5).ravel()


def otsu(v: np.ndarray) -> tuple[float, float]:
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


def prototipos(d: np.ndarray, k: int) -> np.ndarray:
    from sklearn.cluster import KMeans
    k = max(1, min(k, len(d)))
    return KMeans(n_clusters=k, n_init=5, random_state=0).fit(d).cluster_centers_


def clasificar(d: np.ndarray, comida: np.ndarray, fondo: np.ndarray) -> tuple[np.ndarray, float]:
    """Cada zona es comida si su prototipo más parecido es de comida. Devuelve (máscara, confianza 0-1)."""
    dist = lambda protos: np.min(np.linalg.norm(d[:, None, :] - protos[None], axis=2), axis=1)
    dc, dg = dist(comida), dist(fondo)
    return dc < dg, float(np.mean(np.abs(dg - dc) / (dg + dc + 1e-8)))


def analizar_referencia(d: np.ndarray, aspecto: np.ndarray) -> dict:
    """Separa comida y fondo en la foto de referencia. Lanza ValueError si no se distingue la comida."""
    umbral, claridad = otsu(aspecto)
    comida = alisar(aspecto > umbral)
    adv = None
    if claridad < 0.35:
        adv = "Hay poco contraste entre la comida y el plato: toma la foto desde arriba, con buena luz y la bandeja completa."
    if comida.sum() < 8 or comida.mean() > 0.9:
        adv = "No se distingue bien la comida en la foto de referencia: vuelve a tomarla más cerca y con mejor luz."
    if comida.sum() < 8 or (~comida).sum() < 8:
        raise ValueError(adv)
    p_comida, p_fondo = prototipos(d[comida], 4), prototipos(d[~comida], 4)
    comida, _ = mascara_comida(d, p_comida, p_fondo)             # misma regla que se usará con las bandejas
    return {"comida": comida, "p_comida": p_comida, "p_fondo": p_fondo, "f_ref": float(comida.mean()), "advertencia": adv}


FACTOR_UMBRAL_COLOR = 0.5      # una zona es comida si se aleja del color de la bandeja al menos la mitad de lo que se aleja la comida típica


def color_bandeja(fondo: np.ndarray) -> np.ndarray:
    """Color (RGB 0-1) de la bandeja/plato: el promedio del color de los prototipos de fondo de la referencia."""
    return fondo[:, -3:].mean(axis=0) / PESO_COLOR


def umbral_color(comida: np.ndarray, fondo: np.ndarray) -> float:
    """Distancia de color mínima para considerar que una zona no es bandeja: la mitad de lo que se aleja la comida típica."""
    tray = color_bandeja(fondo)
    return FACTOR_UMBRAL_COLOR * float(np.median(np.linalg.norm(comida[:, -3:] / PESO_COLOR - tray, axis=1)))


def mascara_comida(d: np.ndarray, comida: np.ndarray, fondo: np.ndarray) -> tuple[np.ndarray, float]:
    """(máscara, confianza). Una zona cuenta como comida si su prototipo más parecido es de comida Y además su color se
    aleja del color de la bandeja: así las manchas de salsa, migas y la grasa que quedan donde ya se comió no cuentan.
    Se usa igual en la referencia y en las bandejas, así la misma foto llena comparada consigo misma da 100 %."""
    es_comida, confianza = clasificar(d, comida, fondo)
    lejos_de_bandeja = np.linalg.norm(d[:, -3:] / PESO_COLOR - color_bandeja(fondo), axis=1) > umbral_color(comida, fondo)
    return alisar(es_comida & lejos_de_bandeja), confianza


def analizar_bandeja(d: np.ndarray, comida: np.ndarray, fondo: np.ndarray, f_ref: float) -> tuple[np.ndarray, float, float]:
    """(máscara de comida, % restante, confianza). Todo sale de los prototipos de la referencia, por eso el celular
    aplica la misma regla sin conexión."""
    es_comida, confianza = mascara_comida(d, comida, fondo)
    restante = float(min(100.0, 100.0 * es_comida.mean() / f_ref)) if f_ref > 0 else 0.0
    return es_comida, restante, confianza


def mascara_lista(m: np.ndarray) -> list:
    return m.reshape(REJ, REJ).astype(int).tolist()


# ----------------------------- registros hechos en el celular -----------------------------

def validar_id_cliente(cid: str) -> str:
    if not isinstance(cid, str) or not _ID_CLIENTE.match(cid):
        raise ValueError("cliente_id inválido (8-64 letras, números o guiones)")
    return cid


def prototipos_validos(v, nombre: str) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != DIM or not 1 <= a.shape[0] <= 8 or not np.isfinite(a).all():
        raise ValueError(f"«{nombre}» debe ser una lista de 1 a 8 vectores de {DIM} números")
    return a.astype(np.float32)


def validar_referencia_movil(p: dict) -> tuple[str, float]:
    """Comprueba turno, fecha, plato y f_ref. Devuelve (plato, f_ref)."""
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
    return plato, f_ref


def validar_bandeja_movil(p: dict) -> tuple[float, float]:
    restante, confianza = float(p.get("restante", -1)), float(p.get("confianza", -1))
    if not (0 <= restante <= 100) or not (0 <= confianza <= 1):
        raise ValueError("restante debe estar entre 0 y 100 y confianza entre 0 y 1")
    return restante, confianza


def carpeta_valida(carpeta: str, fid: str) -> bool:
    return carpeta in ("ref", "bandeja") and fid.isalnum()
