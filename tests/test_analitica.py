"""Pruebas de los modelos de IA con datos controlados (sin red ni bases de datos).

Los casos de uso reciben puertos falsos: datos de menús en memoria y un clima sin internet.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.application.analitica.agrupamiento import ServicioAgrupamiento
from app.application.analitica.regresion import ServicioRegresion


def _filas(n_dias=14, demanda=lambda d, p: 10 + p * 5):
    hoy = date.today()
    out = []
    for i in range(n_dias):
        f = (hoy - timedelta(days=n_dias - i)).isoformat()
        for p in range(3):
            out.append({"fecha": f, "turno": "ALMUERZO", "platoId": f"plato-{p}", "cupo": 60, "apartadas": demanda(i, p)})
    return out


class DatosFalsos:
    def __init__(self):
        self._filas = []

    def filas(self, ttl=15.0):
        return self._filas

    def firma(self):
        return f"{len(self._filas)}:{sum(x['apartadas'] for x in self._filas)}"

    def fuente_ok(self):
        return True


class ClimaSinRed:
    def temperaturas(self):
        return {}

    def temperatura(self, f):
        return None

    def disponible(self):
        return False


@pytest.fixture
def sin_red():
    """Modelos recién creados, sin clima; las pruebas chicas usan pocos datos (el mínimo real, 2000, se prueba abajo)."""
    datos = DatosFalsos()
    return SimpleNamespace(datos=datos,
                           regresion=ServicioRegresion(datos, ClimaSinRed(), min_muestras=10),
                           agrupamiento=ServicioAgrupamiento(datos, lambda: {}, min_registros=1))


def _con(modelos, filas):
    modelos.datos._filas = filas


def test_regresion_pocos_datos_no_entrena(sin_red):
    _con(sin_red, _filas(2))
    e = sin_red.regresion.estado()
    assert e["suficiente"] is False and "mensaje" in e


def test_regresion_aprende_el_patron_de_los_datos(sin_red):
    _con(sin_red, _filas(14))                      # demanda 10 / 15 / 20 según el plato
    e = sin_red.regresion.estado()
    assert e["suficiente"] and e["metricas"]["confiable"] is True
    p0 = sin_red.regresion.predecir(date.today().isoformat(), "plato-0")["racionesEstimadas"]
    p2 = sin_red.regresion.predecir(date.today().isoformat(), "plato-2")["racionesEstimadas"]
    assert p2 > p0 and 7 <= p0 <= 14 and 16 <= p2 <= 24


def test_plan_usa_menus_futuros(sin_red):
    futuro = (date.today() + timedelta(days=2)).isoformat()
    _con(sin_red, _filas(14) + [{"fecha": futuro, "turno": "ALMUERZO", "platoId": "plato-1", "cupo": 60, "apartadas": 0}])
    plan = sin_red.regresion.estado()["plan"]
    assert len(plan) == 1 and plan[0]["fecha"] == futuro and plan[0]["sugerida"] <= 60


def test_agrupamiento_separa_platos_populares_de_los_ignorados(sin_red):
    filas = []
    f = (date.today() - timedelta(days=1)).isoformat()
    for i in range(4):
        filas.append({"fecha": f, "turno": "ALMUERZO", "platoId": f"popular-{i}", "cupo": 50, "apartadas": 45 + i})
        filas.append({"fecha": f, "turno": "ALMUERZO", "platoId": f"ignorado-{i}", "cupo": 50, "apartadas": i})
    _con(sin_red, filas)
    r = sin_red.agrupamiento.calcular()
    accion = {p["plato"]: p["accion"] for p in r["puntos"]}
    assert r["suficiente"] and r["k"] == 2
    assert all(accion[f"popular-{i}"] == "Mantener" for i in range(4))
    assert all(accion[f"ignorado-{i}"] != "Mantener" for i in range(4))


def test_agrupamiento_con_pocos_platos(sin_red):
    _con(sin_red, _filas(1)[:2])
    assert sin_red.agrupamiento.calcular()["suficiente"] is False


def _tres_anios(n_dias=1100):
    """3 años de menús con patrón real: más demanda lunes-miércoles, menos viernes/sábado, plato 0 más popular."""
    hoy = date.today()
    out = []
    for i in range(n_dias):
        d = hoy - timedelta(days=n_dias - i)
        if d.weekday() == 6:
            continue
        for turno in ("DESAYUNO", "ALMUERZO", "CENA"):
            for p in range(2 if turno == "ALMUERZO" else 1):
                base = {"DESAYUNO": 6, "ALMUERZO": 18, "CENA": 8}[turno] - 5 * p
                dia = (1.2, 1.2, 1.1, 1.0, 0.8, 0.5)[d.weekday()]
                out.append({"fecha": d.isoformat(), "turno": turno, "platoId": f"plato-{turno[0]}{p}", "cupo": 40,
                            "apartadas": max(0, round(base * dia))})
    return out


def test_minimo_2000_registros_para_entrenar(sin_red):
    sin_red.regresion.min_muestras = 2000
    _con(sin_red, _filas(14))                      # 42 registros: no alcanza
    e = sin_red.regresion.estado()
    assert e["suficiente"] is False and "2000" in e["mensaje"]


def test_prediccion_con_tres_anios_de_datos(sin_red):
    sin_red.regresion.min_muestras = 2000
    filas = _tres_anios()
    assert len(filas) >= 2000
    _con(sin_red, filas)
    e = sin_red.regresion.estado()
    assert e["suficiente"] and e["muestras"] >= 2000
    assert e["metricas"]["confiable"] is True and e["metricas"]["validacion"] == "5-fold"


def test_agrupamiento_exige_2000_registros(sin_red):
    sin_red.agrupamiento.min_registros = 2000
    _con(sin_red, _filas(14))
    assert sin_red.agrupamiento.calcular()["suficiente"] is False
    _con(sin_red, _tres_anios())
    r = sin_red.agrupamiento.calcular()
    assert r["suficiente"] and r["registros"] >= 2000
