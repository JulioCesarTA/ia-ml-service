"""Desperdicio por sector: la cuenta de cada sector y el promedio, y que el modelo guardado se pueda usar."""
import json
from pathlib import Path

import numpy as np
import pytest

from app.domain.analitica import sectores as sec
from app.domain.analitica.vision import REJ

MODELO = Path(__file__).resolve().parents[1] / "app" / "infrastructure" / "adapters" / "outbound" / "tensorflow" / "modelo_sectores.json"


def _mapa(bloques):
    """Clases por zona con bloques rectangulares {clase: (fila0, fila1, col0, col1)}."""
    m = np.zeros((REJ, REJ), int)
    for clase, (f0, f1, c0, c1) in bloques.items():
        m[f0:f1, c0:c1] = sec.CLASES.index(clase)
    return m.ravel()


def test_por_sector_y_promedio():
    ref = _mapa({"arroz": (30, 50, 2, 22), "proteina": (30, 50, 26, 54), "postre": (2, 20, 2, 16)})
    zonas = sec.sectores_referencia(ref)
    bandeja = _mapa({"arroz": (30, 40, 2, 22), "proteina": (30, 50, 26, 54)})     # medio arroz, todo el pollo, sin postre
    filas, promedio = sec.comparar(zonas, bandeja, sec.nombres_validos({"proteina": "pollo"}))
    r = {f["clase"]: f["restante"] for f in filas}
    assert r == {"arroz": 50.0, "proteina": 100.0, "postre": 0.0}
    assert promedio == pytest.approx(50.0)
    assert next(f for f in filas if f["clase"] == "proteina")["nombre"] == "pollo"


def test_sector_chico_no_cuenta():
    ref = _mapa({"arroz": (30, 50, 2, 22), "ensalada": (0, 3, 0, 3)})          # 9 zonas de ensalada: ruido
    assert set(sec.sectores_referencia(ref)) == {"arroz"}


def test_moda_quita_zonas_sueltas():
    m = np.zeros(REJ * REJ, int); m[REJ * 10 + 10] = 1
    assert sec.moda(m).sum() == 0


def test_sectores_del_celular():
    assert sec.sectores_validos([{"clase": "arroz", "nombre": "arroz", "restante": 33}])[0]["restante"] == 33.0
    with pytest.raises(ValueError):
        sec.sectores_validos([{"clase": "sopa", "restante": 10}])
    with pytest.raises(ValueError):
        sec.sectores_validos([{"clase": "arroz", "restante": 140}])


@pytest.mark.skipif(not MODELO.exists(), reason="sin modelo entrenado")
def test_modelo_guardado_se_puede_usar():
    modelo = json.loads(MODELO.read_text(encoding="utf-8"))
    assert modelo["clases"] == list(sec.CLASES)
    x = np.random.default_rng(0).normal(size=(REJ * REJ, len(modelo["media"]))).astype(np.float32)
    pred = sec.clasificar_zonas(x, modelo)
    assert pred.shape == (REJ * REJ,) and pred.min() >= 0 and pred.max() < len(sec.CLASES)
    assert sec.nombres_validos(None, modelo.get("nombres"))["proteina"] == "pollo apanado"
