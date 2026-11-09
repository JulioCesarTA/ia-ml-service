"""Quién puede reservar por Telegram: estudiantes y administradores; el resto no ve el botón ni puede reservar."""
from app.services import asistente


def _botones(teclado):
    return [b["callback_data"] for fila in teclado for b in fila]


def test_el_administrador_ve_el_boton_de_reservar():
    assert "m:res" in _botones(asistente._teclado(["administrador"]))


def test_el_estudiante_ve_el_boton_de_reservar():
    assert "m:res" in _botones(asistente._teclado(["estudiante"]))


def test_cocina_y_caja_no_reservan():
    for rol in ("cocina_almacen", "cajero", "nutricionista"):
        assert "m:res" not in _botones(asistente._teclado([rol]))
        assert not asistente._puede_reservar([rol])


def test_el_administrador_puede_elegir_turno(monkeypatch):
    enviados = []
    monkeypatch.setattr(asistente.tg, "enviar", lambda cid, texto, botones=None: enviados.append((texto, botones)))
    asistente._elegir_turno("1", {"roles": ["administrador"]})
    assert enviados and "turno" in enviados[0][0].lower()


def test_un_cocinero_recibe_un_aviso_claro(monkeypatch):
    enviados = []
    monkeypatch.setattr(asistente.tg, "enviar", lambda cid, texto, botones=None: enviados.append(texto))
    asistente._elegir_turno("1", {"roles": ["cocina_almacen"]})
    assert "solo para estudiantes y administradores" in enviados[0]
