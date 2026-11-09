"""Adaptadores y armado de la aplicación: base local, traducción de errores de red, Telegram por n8n y la raíz de
composición (sin red real)."""
import sqlite3

import httpx
import pytest

from app.application.ports.errores import ErrorDeRed
from app.application.telegram_bot import ServicioTelegram
from app.infrastructure.adapters.inbound.http.autenticacion import identidad_bearer
from app.infrastructure.adapters.outbound.http import n8n as n8n_mod
from app.infrastructure.adapters.outbound.http import telegram as tg_mod
from app.infrastructure.adapters.outbound.sqlite.base import BaseLocal
from app.main import contenedor


# ----------------------------- SQLite -----------------------------

def test_la_base_vieja_se_migra_sin_perder_datos(tmp_path):
    """Una base creada antes de las columnas nuevas recibe los ALTER TABLE e índices, y conserva sus filas."""
    ruta = tmp_path / "agentes.db"
    c = sqlite3.connect(ruta)
    c.executescript("""
        CREATE TABLE outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, texto TEXT, propuesta_id TEXT,
          con_botones INTEGER DEFAULT 0, creado REAL, intentos INTEGER DEFAULT 0);
        CREATE TABLE ref_porcion(id TEXT PRIMARY KEY, plato_id TEXT, fecha TEXT, turno TEXT, creado REAL, f_ref REAL, advertencia TEXT);
        INSERT INTO outbox(texto) VALUES('hola');
    """)
    c.commit(); c.close()
    BaseLocal(str(tmp_path))
    c = sqlite3.connect(ruta)
    assert "chat_id" in [r[1] for r in c.execute("PRAGMA table_info(outbox)")]
    assert {"foto_key", "origen", "cliente_id"} <= {r[1] for r in c.execute("PRAGMA table_info(ref_porcion)")}
    indices = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"ux_ref_porcion_cliente", "ux_bandejas_cliente"} <= indices
    assert c.execute("SELECT texto FROM outbox").fetchone()[0] == "hola"


def test_el_respaldo_es_una_copia_valida_de_la_base(tmp_path):
    datos = contenedor.respaldo._base.copia_consistente()
    (tmp_path / "copia.db").write_bytes(datos)
    tablas = {r[0] for r in sqlite3.connect(tmp_path / "copia.db").execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"propuestas", "outbox", "config", "chats", "pagos_tg", "ref_porcion", "dispositivos", "bandejas"} <= tablas


def test_sin_s3_el_respaldo_no_hace_nada(monkeypatch):
    monkeypatch.delenv("S3_BANDEJAS_BUCKET", raising=False)
    assert contenedor.respaldo.respaldar() is None


# ----------------------------- errores de red -----------------------------

def test_n8n_traduce_la_falta_de_red_y_los_errores_del_flujo(monkeypatch):
    monkeypatch.setenv("N8N_URL", "http://n8n:5678")

    def sin_red(*a, **k):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(n8n_mod.httpx, "post", sin_red)
    with pytest.raises(ErrorDeRed, match="sin red") as e:
        n8n_mod.ClienteN8n().llamar("notificar", {})
    assert e.value.tipo == "ConnectError"            # el estado del push sigue mostrando el error original
    monkeypatch.setattr(n8n_mod.httpx, "post", lambda *a, **k: httpx.Response(503, request=httpx.Request("POST", "http://x")))
    with pytest.raises(ErrorDeRed, match="respondió 503"):
        n8n_mod.ClienteN8n().llamar("notificar", {})


def test_telegram_directo_traduce_la_falta_de_red(monkeypatch):
    monkeypatch.delenv("N8N_URL", raising=False)

    def sin_red(*a, **k):
        raise httpx.ReadTimeout("lento")
    monkeypatch.setattr(tg_mod.httpx, "post", sin_red)
    with pytest.raises(ErrorDeRed):
        tg_mod.ClienteTelegramHttp(n8n_mod.ClienteN8n()).llamar("sendMessage", chat_id="1", text="x")


# ----------------------------- Telegram por n8n -----------------------------

class ClienteTelegramFalso:
    def __init__(self):
        self.llamadas = []

    def configurado(self):
        return True

    def llamar(self, metodo, espera=15, **payload):
        self.llamadas.append(metodo)
        return {}

    def enviar_foto(self, chat, png, pie):
        pass


def test_procesar_evento_devuelve_las_acciones_en_vez_de_llamar_a_telegram():
    cliente = ClienteTelegramFalso()
    bot = ServicioTelegram(cliente, contenedor.cola, contenedor.identidad, contenedor.propuestas, contenedor.repo_config)
    bot.asistente = type("A", (), {"mensaje": lambda self, m: bot.enviar(str(m["chat"]["id"]), "hola")})()
    acciones = bot.procesar_evento({"message": {"chat": {"id": 7}, "text": "/start"}})
    assert acciones == [{"metodo": "sendMessage", "datos": {"chat_id": "7", "text": "hola"}}]
    assert cliente.llamadas == []


def test_un_boton_de_propuesta_de_alguien_que_no_es_admin_se_rechaza():
    bot = ServicioTelegram(ClienteTelegramFalso(), contenedor.cola, contenedor.identidad, contenedor.propuestas, contenedor.repo_config)
    acciones = bot.procesar_evento({"callback_query": {"id": "c1", "data": "ap:xx", "message": {"chat": {"id": 999}, "message_id": 1}}})
    assert acciones == [{"metodo": "answerCallbackQuery",
                         "datos": {"callback_query_id": "c1", "text": "Solo un administrador puede aprobar o rechazar"}}]


# ----------------------------- entrada HTTP y raíz de composición -----------------------------

def test_jwt_ilegible_o_ausente_no_identifica_a_nadie():
    assert identidad_bearer(None) == (None, [])
    assert identidad_bearer("Basic abc") == (None, [])
    assert identidad_bearer("Bearer x.%%%.y") == (None, [])


def test_la_raiz_de_composicion_conecta_los_casos_de_uso():
    c = contenedor
    assert c.telegram.asistente is c.asistente
    assert c.avisos.propuestas is c.propuestas and c.avisos.cola is c.cola and c.telegram.cola is c.cola
    assert c.push._dispositivos is c.repo_dispositivos and c.push._flujos is c.n8n
    assert c.base.ruta.endswith("agentes.db")
