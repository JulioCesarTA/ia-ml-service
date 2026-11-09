"""Registro de referencias y bandejas hechas en el celular: validaciones y que reenviar no duplique (sin red ni S3)."""
import uuid

import numpy as np
import pytest

from app.domain import fotos
from app.main import contenedor

vision = contenedor.vision                   # caso de uso ServicioVision con sus adaptadores reales (SQLite, disco, S3)
repo_vision = contenedor.repo_vision
s3_fotos = contenedor.s3

DIM = vision.DIM


def _protos(k=2, valor=0.1):
    return (np.full((k, DIM), valor)).tolist()


def _ref(**kw):
    d = {"cliente_id": f"ref-{uuid.uuid4()}", "plato_id": "plato-asado", "fecha": "2026-11-05", "turno": "ALMUERZO",
         "f_ref": 0.4, "comida": _protos(valor=0.2), "fondo": _protos(valor=0.8)}
    d.update(kw)
    return d


def test_referencia_movil_se_guarda_y_no_se_duplica():
    d = _ref()
    a = vision.registrar_referencia_movil(d)
    b = vision.registrar_referencia_movil(d)                     # reintento sin conexión: mismo cliente_id
    assert a["repetido"] is False and b["repetido"] is True and a["id"] == b["id"]
    r = repo_vision.referencia(a["id"])
    assert r["origen"] == "movil" and r["plato_id"] == "plato-asado" and r["cliente_id"] == d["cliente_id"]


@pytest.mark.parametrize("cambio", [
    {"turno": "MERIENDA"}, {"fecha": "05/11/2026"}, {"f_ref": 0}, {"f_ref": 1.5}, {"plato_id": ""},
    {"comida": [[0.1] * 10]}, {"fondo": []}, {"comida": [[float("nan")] * DIM]}, {"cliente_id": "corto"},
])
def test_referencia_movil_valida_los_datos(cambio):
    with pytest.raises(ValueError):
        vision.registrar_referencia_movil(_ref(**cambio))


def test_bandeja_movil_requiere_referencia_y_no_se_duplica():
    ref = vision.registrar_referencia_movil(_ref())
    pedido = {"cliente_id": f"ban-{uuid.uuid4()}", "ref_id": ref["id"], "restante": 37.5, "confianza": 0.8}
    a = vision.registrar_bandeja_movil(pedido)
    b = vision.registrar_bandeja_movil(pedido)
    assert a["repetido"] is False and b["repetido"] is True and a["id"] == b["id"]
    with pytest.raises(LookupError):
        vision.registrar_bandeja_movil({**pedido, "cliente_id": f"ban-{uuid.uuid4()}", "ref_id": "noexiste"})
    for malo in ({"restante": 120}, {"restante": -1}, {"confianza": 2}):
        with pytest.raises(ValueError):
            vision.registrar_bandeja_movil({**pedido, "cliente_id": f"ban-{uuid.uuid4()}", **malo})


def test_bandeja_movil_cuenta_en_el_resumen():
    ref = vision.registrar_referencia_movil(_ref(plato_id="plato-prueba-movil"))
    antes = vision.resumen()["bandejas"]
    vision.registrar_bandeja_movil({"cliente_id": f"ban-{uuid.uuid4()}", "ref_id": ref["id"], "restante": 20, "confianza": 0.9})
    assert vision.resumen()["bandejas"] == antes + 1


def test_paquete_movil_trae_las_referencias_con_sus_prototipos():
    ref = vision.registrar_referencia_movil(_ref(plato_id="plato-paquete"))
    p = vision.paquete_movil(200)
    r = next(x for x in p["referencias"] if x["id"] == ref["id"])
    assert p["dim"] == DIM == 147 and p["rejilla"] == 56
    assert np.array(r["comida"]).shape == (2, DIM) and np.array(r["fondo"]).shape == (2, DIM) and r["fRef"] == 0.4


def test_sin_s3_configurado_la_subida_avisa_y_la_foto_no_se_rompe(monkeypatch):
    monkeypatch.delenv("S3_BANDEJAS_BUCKET", raising=False)
    assert s3_fotos.configurado() is False
    with pytest.raises(RuntimeError):
        vision.url_subida("bandeja", f"ban-{uuid.uuid4()}")
    assert s3_fotos.subir("bandejas/2026/11/x.jpg", b"x") is False
    assert vision.url_foto("bandeja", "inexistente") is None


def test_claves_de_s3_solo_dentro_de_las_carpetas_permitidas():
    for mala in ("../etc/passwd", "otra/carpeta/x.jpg", "bandejas/../x", "bandejas/", ""):
        assert not fotos.CLAVE_VALIDA.match(mala)
    assert fotos.CLAVE_VALIDA.match("bandejas/2026/11/abc123.jpg")
    assert fotos.clave_foto("ref", "abc", "2026-11-05") == "referencias/2026/11/abc.jpg"
