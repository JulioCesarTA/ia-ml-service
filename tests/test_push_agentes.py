"""Al pulsar «Ejecutar» en un agente, los administradores reciben un push en el celular."""
import pytest

from app.services.agentes import avisos


@pytest.fixture
def enviados(monkeypatch):
    lista = []
    monkeypatch.setattr(avisos.push, "enviar_a_roles", lambda roles, titulo, cuerpo, datos=None: lista.append((roles, titulo, cuerpo, datos)))
    monkeypatch.setattr(avisos.telegram_bot, "encolar", lambda *a, **k: None)
    return lista


def _plan(semana):
    return {"semanaInicio": semana, "propuesta": [
        {"fecha": semana, "turno": "ALMUERZO", "platoId": "plato-pollo", "cumpleRequisitosNutricionales": True, "aprovechaInsumosPorVencer": False}]}


def test_menu_propuesto_avisa_a_los_administradores(enviados):
    avisos.proponer_menu(_plan("2031-01-05"), forzar=True)
    assert len(enviados) == 1
    roles, titulo, _, datos = enviados[0]
    assert roles == ["administrador"] and titulo == "Menú propuesto" and datos["tipo"] == "propuesta"


def test_inventario_con_alerta_avisa_a_admin_y_cocina(enviados):
    r = {"requiereAviso": True, "severidad": "ALTA", "claveAlerta": "k-push-1", "mensajeAdmin": "Stock bajo",
         "ordenesBorrador": [{"nombre": "arroz"}], "totalBorradorBs": 120,
         "insumosEnRiesgo": [{"nombre": "arroz"}], "lotesPorVencer": []}
    avisos.proponer_inventario(r, forzar=True)
    assert len(enviados) == 1 and set(enviados[0][0]) == {"administrador", "cocina_almacen"}


def test_inventario_sin_detalle_avisa_igual_al_administrador(enviados):
    r = {"requiereAviso": True, "severidad": "MEDIA", "claveAlerta": "k-push-2", "mensajeAdmin": "Compra",
         "ordenesBorrador": [{"nombre": "sal"}], "totalBorradorBs": 30, "insumosEnRiesgo": [], "lotesPorVencer": []}
    avisos.proponer_inventario(r, forzar=True)
    assert len(enviados) == 1 and enviados[0][0] == ["administrador"]


def test_inventario_sin_alertas_responde_al_ejecutar(enviados):
    assert avisos.proponer_inventario({"requiereAviso": False}, forzar=True) is None
    assert len(enviados) == 1 and "Sin alertas" in enviados[0][2]


def test_inventario_sin_alertas_programado_no_molesta(enviados):
    avisos.proponer_inventario({"requiereAviso": False})
    assert enviados == []


def test_monitor_con_hallazgos_avisa(enviados):
    r = {"resumenEjecutivo": "Desperdicio alto", "hallazgos": [{"severidad": "ALTA", "mensaje": "m-push-1", "recomendacion": "revisar"}]}
    avisos.avisar_monitor(r, forzar=True)
    assert len(enviados) == 1 and enviados[0][0] == ["administrador"] and "1 hallazgo" in enviados[0][2]


def test_monitor_sin_hallazgos_responde_al_ejecutar(enviados):
    assert avisos.avisar_monitor({"hallazgos": []}, forzar=True) is None
    assert len(enviados) == 1 and "Sin novedades" in enviados[0][2]


def test_un_fallo_de_firebase_no_detiene_al_agente(monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("firebase caído")
    monkeypatch.setattr(avisos.push, "enviar_a_roles", falla)
    monkeypatch.setattr(avisos.telegram_bot, "encolar", lambda *a, **k: None)
    res = avisos.proponer_menu(_plan("2031-02-02"), forzar=True)
    assert res["nueva"] is True
