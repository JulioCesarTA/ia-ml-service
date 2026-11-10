"""Entrena la red de SECTORES (mandarina, puré, ensalada, arroz, pollo) con las fotos de la carpeta pollo y la valida
contra etiquetas.csv (lo que quedó de cada sector en cada foto).

Carpeta: pagos-tickets-service/im/pollo  ->  bandeja_llena.jpeg (la porción completa) + bandeja_01..10.jpg + etiquetas.csv
Etiquetas por zona (56x56): comida vs bandeja gris por color (saturación o alejarse del gris) y sector por compartimento.
Validación: cada foto se mide con un modelo entrenado SIN ella y se compara con el CSV. Luego se entrena con todas y
se guarda el modelo en el servicio y en la app (va dentro de ambos: funciona sin internet).

Dos pasos (la CNN de TensorFlow está en el pod; entrenar es más rápido en una PC):
    # en el pod de ia-ml: características de las 11 fotos
    FOTOS_POLLO=/tmp/pollo python herramientas/entrenar_sectores.py --exportar /tmp/feat_pollo.npz
    # en la PC (numpy + scikit-learn): valida, entrena y guarda
    python herramientas/entrenar_sectores.py --caracteristicas feat_pollo.npz
"""
import csv
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app.domain.analitica import sectores as sec  # noqa: E402
from app.domain.analitica.vision import LADO, REJ  # noqa: E402

CARPETA = Path(os.environ.get("FOTOS_POLLO", RAIZ.parent / "pagos-tickets-service" / "im" / "pollo"))
SALIDAS = [RAIZ / "app" / "infrastructure" / "adapters" / "outbound" / "tensorflow" / "modelo_sectores.json",
           RAIZ.parent / "comedor-clientes" / "mobile" / "app-flutter" / "assets" / "modelos" / "modelo_sectores.json"]
# compartimentos de la bandeja (fracción de la foto) -> sector
COMPARTIMENTOS = {"postre": (0.03, 0.02, 0.335, 0.43), "guarnicion": (0.335, 0.02, 0.665, 0.43), "ensalada": (0.665, 0.02, 0.98, 0.43),
                  "arroz": (0.02, 0.43, 0.43, 0.95), "proteina": (0.43, 0.43, 0.98, 0.95)}
COLUMNA_CSV = {"postre": "mandarina", "guarnicion": "pure", "ensalada": "ensalada", "arroz": "arroz", "proteina": "pollo_apanado"}
NOMBRES = {"postre": "mandarina", "guarnicion": "puré", "ensalada": "ensalada", "arroz": "arroz", "proteina": "pollo apanado"}
UMBRAL_SAT, UMBRAL_COLOR = 0.26, 0.14       # comida: saturada o lejos del gris neutro (elegidos contra el CSV)
CONFIG = {"oculta": 32, "alfa": 1e-2, "redes": 3}


def fotos() -> dict[str, Path]:
    return {"llena": CARPETA / "bandeja_llena.jpeg", **{p.stem: p for p in sorted(CARPETA.glob("bandeja_[0-9]*.jpg"))}}


def abrir(p: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(p)).convert("RGB")


def etiquetas(img: Image.Image) -> np.ndarray:
    """Clase de cada zona: 0 bandeja, o el sector del compartimento donde hay comida."""
    pq = img.resize((LADO, LADO)); paso = LADO // REJ
    zona = lambda v: v.reshape(REJ, paso, REJ, paso).mean(axis=(1, 3)).ravel()
    sat = zona(np.asarray(pq.convert("HSV"), dtype=np.float32)[..., 1] / 255.0)
    rgb = np.stack([zona(np.asarray(pq, dtype=np.float32)[..., i] / 255.0) for i in range(3)], 1)
    comida = (sat > UMBRAL_SAT) | (np.abs(rgb - rgb.mean(axis=1, keepdims=True)).sum(axis=1) > UMBRAL_COLOR)
    m = comida.reshape(REJ, REJ).astype(np.float32); p = np.pad(m, 1, mode="edge")
    comida = (sum(p[i:i + REJ, j:j + REJ] for i in range(3) for j in range(3)) >= 5).ravel()
    c = (np.arange(REJ) + 0.5) / REJ
    X, Y = (a.ravel() for a in np.meshgrid(c, c))
    sector = np.zeros(REJ * REJ, int)
    for nombre, (x0, y0, x1, y1) in COMPARTIMENTOS.items():
        sector[(X >= x0) & (X < x1) & (Y >= y0) & (Y < y1)] = sec.CLASES.index(nombre)
    return np.where(comida, sector, 0)


def caracteristicas() -> dict[str, np.ndarray]:
    if "--caracteristicas" in sys.argv:
        with np.load(sys.argv[sys.argv.index("--caracteristicas") + 1]) as f:
            return {k: f[k] for k in f.files}
    from app.infrastructure.adapters.outbound.tensorflow.procesador_imagenes import ProcesadorTensorFlow
    cnn = ProcesadorTensorFlow()
    salida = {}
    for k, p in fotos().items():
        d, _, s, t = cnn.zonas_completas(abrir(p))
        salida[k] = sec.entrada(d, s, t)
    return salida


def entrenar(F: dict, L: dict, nombres: list[str]) -> dict:
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    X = np.vstack([F[n] for n in nombres]); y = np.concatenate([L[n] for n in nombres])
    esc = StandardScaler().fit(X); Z = esc.transform(X)
    r = lambda a, n=5: np.round(np.asarray(a, dtype=float), n).tolist()
    redes = []
    for semilla in range(CONFIG["redes"]):
        m = MLPClassifier(hidden_layer_sizes=(CONFIG["oculta"],), alpha=CONFIG["alfa"], max_iter=500, random_state=semilla).fit(Z, y)
        redes.append({"W1": r(m.coefs_[0]), "b1": r(m.intercepts_[0]), "W2": r(m.coefs_[1]), "b2": r(m.intercepts_[1])})
    return {"clases": list(sec.CLASES), "media": r(esc.mean_, 6), "escala": r(esc.scale_, 6), "redes": redes,
            "sesgo_fondo": 1.0, "nombres": NOMBRES}


def medir(modelo: dict, F: dict, foto: str) -> dict[str, float]:
    """% que quedó de cada sector, con la misma cuenta que el servicio y el celular."""
    zonas_ref = sec.sectores_referencia(sec.clasificar_zonas(F["llena"], modelo))
    filas, _ = sec.comparar(zonas_ref, sec.clasificar_zonas(F[foto], modelo), NOMBRES)
    return {f["clase"]: f["restante"] for f in filas}


def _sin(args):
    F, L, foto = args
    return foto, medir(entrenar(F, L, [k for k in F if k != foto]), F, foto)


def main():
    F = caracteristicas()
    if "--exportar" in sys.argv:
        destino = sys.argv[sys.argv.index("--exportar") + 1]
        np.savez_compressed(destino, **F)
        print(f"características de {len(F)} fotos en {destino}")
        return
    L = {k: etiquetas(abrir(p)) for k, p in fotos().items()}
    csv_ = {r["archivo"].rsplit(".", 1)[0]: r for r in csv.DictReader(open(CARPETA / "etiquetas.csv", encoding="utf-8"))}
    probar = [k for k in F if k != "llena"]
    with ProcessPoolExecutor(max_workers=min(10, os.cpu_count() or 1)) as ex:
        res = dict(ex.map(_sin, [(F, L, k) for k in probar]))
    print("VALIDACIÓN: cada foto medida por un modelo entrenado SIN ella\n")
    print("foto        " + "".join(f"{COLUMNA_CSV[c]:>18s}" for c in COMPARTIMENTOS))
    errores = []
    for k in probar:
        v = {c: float(csv_[k][COLUMNA_CSV[c]]) for c in COMPARTIMENTOS}
        errores += [abs(res[k].get(c, 0) - v[c]) for c in COMPARTIMENTOS]
        print(f"{k:11s} " + "".join(f"{res[k].get(c, 0):6.0f} (csv{v[c]:4.0f})  " for c in COMPARTIMENTOS))
    error = float(np.mean(errores))
    print(f"\nerror medio por sector: {error:.1f} puntos (peor {max(errores):.0f})")
    modelo = {**entrenar(F, L, list(F)), "error_validacion": round(error, 1)}
    texto = json.dumps(modelo, separators=(",", ":"), ensure_ascii=False)
    for s in SALIDAS:
        s.write_text(texto, encoding="utf-8")
        print(f"modelo guardado en {s}")


if __name__ == "__main__":
    main()
