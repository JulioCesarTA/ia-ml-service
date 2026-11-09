"""Quién puede reservar por Telegram: estudiantes y administradores; el resto no ve el botón ni puede reservar."""
from app.application import asistente
from app.application.asistente import Asistente


class TelegramFalso:
    def __init__(self):
        self.enviados = []

    def enviar(self, cid, texto, botones=None):
        self.enviados.append((texto, botones))


def _asistente(tg):
    return Asistente(tg, identidad=None, propuestas=None, sagas=None, mcp=None, pagos=None, pagos_tg=None,
                     stripe_de_prueba=lambda: False)


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


def test_el_administrador_puede_elegir_turno():
    tg = TelegramFalso()
    _asistente(tg)._elegir_turno("1", {"roles": ["administrador"]})
    enviados = tg.enviados
    assert enviados and "turno" in enviados[0][0].lower()


def test_un_cocinero_recibe_un_aviso_claro():
    tg = TelegramFalso()
    _asistente(tg)._elegir_turno("1", {"roles": ["cocina_almacen"]})
    enviados = [texto for texto, _ in tg.enviados]
    assert "solo para estudiantes y administradores" in enviados[0]
