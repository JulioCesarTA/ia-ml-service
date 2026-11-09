"""Notificaciones push: registro de teléfonos, envío por rol y aviso de stock bajo (Firebase simulado, sin red)."""
import base64
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.application.ports.errores import ErrorDeRed
from app.main import app, contenedor

push = contenedor.push                         # caso de uso ServicioPush
repo_dispositivos = contenedor.repo_dispositivos
avisos = contenedor.avisos
http = TestClient(app)                         # sin `with`: no arranca los hilos de Telegram ni el programador


def registrar(token, usuario=None, roles=None, authorization=None):
    """POST /agentes/push/dispositivo, igual que lo hace el teléfono."""
    cuerpo = {"token": token}
    if usuario is not None:
        cuerpo["usuario"] = usuario
    if roles is not None:
        cuerpo["roles"] = roles
    return http.post("/agentes/push/dispositivo", json=cuerpo, headers={"Authorization": authorization} if authorization else {})


def _jwt(usuario: str, roles: list[str]) -> str:
    cuerpo = base64.urlsafe_b64encode(json.dumps(
        {"preferred_username": usuario, "realm_access": {"roles": roles + ["default-roles-comedor"]}}).encode()).decode().rstrip("=")
    return f"Bearer x.{cuerpo}.y"


def _tok() -> str:
    return "tok-" + uuid.uuid4().hex + "0" * 8          # >= 20 caracteres, único por prueba


@pytest.fixture
def fcm(monkeypatch):
    """Firebase simulado: guarda lo que se enviaría y permite marcar tokens como ya inválidos."""
    enviados, muertos = [], set()
    monkeypatch.setenv("N8N_URL", "http://n8n:5678")

    def falso(token, titulo, cuerpo, datos):
        if token in muertos:
            return False, True
        enviados.append({"token": token, "titulo": titulo, "cuerpo": cuerpo, "datos": datos})
        return True, False
    monkeypatch.setattr(push, "_enviar_fcm", falso)
    return enviados, muertos


def test_registrar_toma_usuario_y_roles_del_token_no_del_cuerpo():
    t = _tok()
    r = registrar(t, usuario="otro", roles=["administrador"], authorization=_jwt("cocinero.demo", ["cocina_almacen"])).json()
    assert r["usuario"] == "cocinero.demo" and r["roles"] == ["cocina_almacen"]   # un teléfono no puede ascenderse a admin
    assert repo_dispositivos.de_usuario("cocinero.demo")[0]["roles"] == ["cocina_almacen"]


def test_sin_token_se_usa_lo_que_dice_el_telefono_pero_solo_roles_conocidos():
    t = _tok()
    r = registrar(t, usuario="sin.jwt", roles=["administrador", "hacker"]).json()
    assert r["roles"] == ["administrador"]


def test_un_token_cambia_de_dueño_si_otra_persona_inicia_sesion_en_el_telefono():
    t = _tok()
    registrar(t, authorization=_jwt("ana", ["estudiante"]))
    registrar(t, authorization=_jwt("beto", ["administrador"]))
    assert repo_dispositivos.de_usuario("ana") == []
    assert repo_dispositivos.de_usuario("beto")[0]["token"] == t


def test_rechaza_tokens_invalidos_y_peticiones_sin_usuario():
    r = registrar("corto", usuario="x")
    assert r.status_code == 400 and r.json()["detail"] == "El token del dispositivo no es válido"
    r = registrar(_tok())
    assert r.status_code == 400 and r.json()["detail"] == "Falta el usuario"


def test_baja_al_cerrar_sesion():
    t = _tok()
    registrar(t, authorization=_jwt("carla", ["administrador"]))
    assert http.post("/agentes/push/baja", json={"token": t}).json()["ok"] is True
    assert http.post("/agentes/push/baja", json={"token": t}).json()["ok"] is False


def test_enviar_a_un_rol_llega_solo_a_los_de_ese_rol(fcm):
    enviados, _ = fcm
    a, c, e = _tok(), _tok(), _tok()
    registrar(a, authorization=_jwt("rol.admin", ["administrador"]))
    registrar(c, authorization=_jwt("rol.cocina", ["cocina_almacen"]))
    registrar(e, authorization=_jwt("rol.estudiante", ["estudiante"]))
    r = push.enviar_a_roles(["administrador", "cocina_almacen"], "Hola", "cuerpo", {"tipo": "x"})
    tokens = {m["token"] for m in enviados}
    assert {a, c} <= tokens and e not in tokens
    assert r["enviados"] >= 2 and r["fallidos"] == 0


def test_un_token_repetido_solo_recibe_una_vez(fcm):
    enviados, _ = fcm
    t = _tok()
    registrar(t, authorization=_jwt("doble", ["administrador", "cocina_almacen"]))
    push.enviar_a_roles(["administrador", "cocina_almacen"], "Hola", "x")
    assert sum(1 for m in enviados if m["token"] == t) == 1


def test_un_token_que_firebase_rechaza_se_borra_solo(fcm):
    _, muertos = fcm
    t = _tok()
    registrar(t, authorization=_jwt("viejo", ["administrador"]))
    muertos.add(t)
    r = push.enviar_a_usuario("viejo", "Hola", "x")
    assert r["fallidos"] == 1 and r["tokensBorrados"] == 1
    assert repo_dispositivos.de_usuario("viejo") == []


def test_los_datos_van_como_texto_y_los_textos_se_recortan(fcm):
    enviados, _ = fcm
    t = _tok()
    registrar(t, authorization=_jwt("datos", ["administrador"]))
    push.enviar_a_usuario("datos", "T" * 500, "C" * 900, {"n": 5, "ok": True})
    m = next(x for x in enviados if x["token"] == t)
    assert m["datos"] == {"n": "5", "ok": "True"} and len(m["titulo"]) == 100 and len(m["cuerpo"]) == 400


def test_el_push_sale_por_n8n_con_vigencia_de_dos_dias(monkeypatch):
    """n8n envía a Firebase. Sin internet en el teléfono, Firebase conserva el aviso 2 días."""
    capturado = {}

    def falso_llamar(webhook, cuerpo, espera=20):
        capturado.update(webhook=webhook, cuerpo=cuerpo)
        return {"ok": True}
    monkeypatch.setenv("N8N_URL", "http://n8n:5678")
    monkeypatch.setattr(contenedor.n8n, "llamar", falso_llamar)
    ok, muerto = push._enviar_fcm("tok" * 10, "T", "C", {"tipo": "stock_bajo"})
    assert ok and not muerto
    assert capturado["webhook"] == "notificar"
    c = capturado["cuerpo"]
    assert c["canal"] == "push" and c["vigencia"] == "172800s" and c["canalAndroid"] == "avisos_comedor"


def test_si_n8n_no_responde_el_push_no_rompe_y_el_token_sigue_valido(monkeypatch):
    def caido(*a, **k):
        raise ErrorDeRed("sin red")
    monkeypatch.setenv("N8N_URL", "http://n8n:5678")
    monkeypatch.setattr(contenedor.n8n, "llamar", caido)
    assert push._enviar_fcm("tok" * 10, "T", "C", {}) == (False, False)


def test_sin_n8n_el_envio_no_rompe_nada(monkeypatch):
    monkeypatch.delenv("N8N_URL", raising=False)
    t = _tok()
    registrar(t, authorization=_jwt("sinfb", ["administrador"]))
    r = push.enviar_a_usuario("sinfb", "Hola", "x")
    assert r["enviados"] == 0 and r["configurado"] is False
    r = http.post("/agentes/push/prueba", json={"usuario": "sinfb"})
    assert r.status_code == 503


def test_stock_bajo_avisa_al_administrador_y_a_cocina_por_push(fcm, monkeypatch):
    enviados, _ = fcm
    monkeypatch.setattr(avisos.propuestas, "registrar", lambda *a, **k: ({"id": "p1", "estado": "PENDIENTE"}, True))
    monkeypatch.setattr(avisos.cola, "encolar", lambda *a, **k: None)
    adm, coc, est = _tok(), _tok(), _tok()
    registrar(adm, authorization=_jwt("stock.admin", ["administrador"]))
    registrar(coc, authorization=_jwt("stock.cocina", ["cocina_almacen"]))
    registrar(est, authorization=_jwt("stock.est", ["estudiante"]))
    r = {"requiereAviso": True, "ordenesBorrador": [{"x": 1}], "totalBorradorBs": 4.0, "severidad": "ALTA",
         "claveAlerta": "k", "mensajeAdmin": "m",
         "insumosEnRiesgo": [{"nombre": "SAL"}, {"nombre": "ACEITE"}, {"nombre": "AZUCAR"}, {"nombre": "HARINA"}],
         "lotesPorVencer": [{"nombre": "ARROZ", "diasRestantes": 1}]}
    avisos.proponer_inventario(r)
    mios = [m for m in enviados if m["token"] in (adm, coc, est)]
    assert {m["token"] for m in mios} == {adm, coc}
    m = mios[0]
    assert m["titulo"] == "Inventario: alerta ALTA"
    assert "SAL, ACEITE, AZUCAR y 1 más" in m["cuerpo"] and "ARROZ (1 d)" in m["cuerpo"]
    assert m["datos"] == {"tipo": "stock_bajo", "propuesta": "p1"}


def test_una_alerta_repetida_no_vuelve_a_notificar(fcm, monkeypatch):
    enviados, _ = fcm
    monkeypatch.setattr(avisos.propuestas, "registrar", lambda *a, **k: ({"id": "p1", "estado": "PENDIENTE"}, False))
    monkeypatch.setattr(avisos.cola, "encolar", lambda *a, **k: None)
    t = _tok()
    registrar(t, authorization=_jwt("repite", ["administrador"]))
    avisos.proponer_inventario({"requiereAviso": True, "ordenesBorrador": [{"x": 1}], "totalBorradorBs": 1, "severidad": "MEDIA",
                                "claveAlerta": "k", "mensajeAdmin": "m", "insumosEnRiesgo": [{"nombre": "SAL"}], "lotesPorVencer": []})
    assert not any(m["token"] == t for m in enviados)


def test_si_firebase_falla_el_agente_sigue(monkeypatch):
    monkeypatch.setattr(avisos.propuestas, "registrar", lambda *a, **k: ({"id": "p1", "estado": "PENDIENTE"}, True))
    monkeypatch.setattr(avisos.cola, "encolar", lambda *a, **k: None)
    def revienta(*a, **k): raise RuntimeError("Firebase caído")
    monkeypatch.setattr(avisos.push, "enviar_a_roles", revienta)
    out = avisos.proponer_inventario({"requiereAviso": True, "ordenesBorrador": [{"x": 1}], "totalBorradorBs": 1, "severidad": "ALTA",
                                      "claveAlerta": "k", "mensajeAdmin": "m", "insumosEnRiesgo": [{"nombre": "SAL"}], "lotesPorVencer": []})
    assert out["nueva"] is True
