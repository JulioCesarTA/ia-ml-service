"""Pruebas de los modelos de IA con datos controlados (sin red ni bases de datos)."""
from datetime import date, timedelta

import pytest

from app.services.analitica import agrupamiento, clima, datos, regresion


def _filas(n_dias=14, demanda=lambda d, p: 10 + p * 5):
    hoy = date.today()
    out = []
    for i in range(n_dias):
        f = (hoy - timedelta(days=n_dias - i)).isoformat()
        for p in range(3):
            out.append({"fecha": f, "turno": "ALMUERZO", "platoId": f"plato-{p}", "cupo": 60, "apartadas": demanda(i, p)})
    return out


@pytest.fixture
def sin_red(monkeypatch):
    monkeypatch.setattr(clima, "temperaturas", lambda: {})
    monkeypatch.setattr(clima, "temperatura", lambda f: None)
    monkeypatch.setattr(clima, "disponible", lambda: False)
    monkeypatch.setattr(datos, "fuente_ok", lambda: True)
    monkeypatch.setattr(regresion, "_modelo", {"firma": None, "dato": None})


def _con(monkeypatch, filas):
    monkeypatch.setattr(datos, "filas", lambda ttl=15.0: filas)
    monkeypatch.setattr(datos, "firma", lambda: f"{len(filas)}:{sum(x['apartadas'] for x in filas)}")


def test_regresion_pocos_datos_no_entrena(monkeypatch, sin_red):
    _con(monkeypatch, _filas(2))
    e = regresion.estado()
    assert e["suficiente"] is False and "mensaje" in e


def test_regresion_aprende_el_patron_de_los_datos(monkeypatch, sin_red):
    _con(monkeypatch, _filas(14))                      # demanda 10 / 15 / 20 según el plato
    e = regresion.estado()
    assert e["suficiente"] and e["metricas"]["confiable"] is True
    p0 = regresion.predecir(date.today().isoformat(), "plato-0")["racionesEstimadas"]
    p2 = regresion.predecir(date.today().isoformat(), "plato-2")["racionesEstimadas"]
    assert p2 > p0 and 7 <= p0 <= 14 and 16 <= p2 <= 24


def test_plan_usa_menus_futuros(monkeypatch, sin_red):
    futuro = (date.today() + timedelta(days=2)).isoformat()
    _con(monkeypatch, _filas(14) + [{"fecha": futuro, "turno": "ALMUERZO", "platoId": "plato-1", "cupo": 60, "apartadas": 0}])
    plan = regresion.estado()["plan"]
    assert len(plan) == 1 and plan[0]["fecha"] == futuro and plan[0]["sugerida"] <= 60


def test_agrupamiento_separa_platos_populares_de_los_ignorados(monkeypatch, sin_red):
    filas = []
    f = (date.today() - timedelta(days=1)).isoformat()
    for i in range(4):
        filas.append({"fecha": f, "turno": "ALMUERZO", "platoId": f"popular-{i}", "cupo": 50, "apartadas": 45 + i})
        filas.append({"fecha": f, "turno": "ALMUERZO", "platoId": f"ignorado-{i}", "cupo": 50, "apartadas": i})
    _con(monkeypatch, filas)
    monkeypatch.setattr(agrupamiento, "_desperdicio_por_plato", lambda: {})
    r = agrupamiento.calcular()
    accion = {p["plato"]: p["accion"] for p in r["puntos"]}
    assert r["suficiente"] and r["k"] == 2
    assert all(accion[f"popular-{i}"] == "Mantener" for i in range(4))
    assert all(accion[f"ignorado-{i}"] != "Mantener" for i in range(4))


def test_agrupamiento_con_pocos_platos(monkeypatch, sin_red):
    _con(monkeypatch, _filas(1)[:2])
    assert agrupamiento.calcular()["suficiente"] is False
