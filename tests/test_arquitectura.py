"""La regla de dependencias de la arquitectura hexagonal se comprueba en cada corrida de pruebas.

    domain  <-  application (+ ports)  <-  infrastructure (adaptadores)  <-  main
"""
import ast
import inspect
import pathlib
import typing

import pytest

from app.application.ports import comedor as p_comedor, externos as p_externos, repositorios as p_repos, sagas as p_sagas

RAIZ = pathlib.Path(__file__).resolve().parents[1] / "app"
PROHIBIDOS_NUCLEO = {"fastapi", "starlette", "pydantic", "httpx", "requests", "boto3", "botocore", "sqlite3",
                     "sqlalchemy", "psycopg", "tensorflow", "PIL", "uvicorn"}


def _modulos(capa: str):
    for f in sorted((RAIZ / capa).rglob("*.py")):
        yield f, ast.parse(f.read_text(encoding="utf-8"))


def _importados(arbol) -> set[str]:
    out = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


@pytest.mark.parametrize("capa", ["domain", "application"])
def test_el_nucleo_no_importa_frameworks_ni_drivers(capa):
    for f, arbol in _modulos(capa):
        malos = {m for m in _importados(arbol) if m.split(".")[0] in PROHIBIDOS_NUCLEO}
        assert not malos, f"{f.relative_to(RAIZ)} importa {malos}"


@pytest.mark.parametrize("capa", ["domain", "application"])
def test_el_nucleo_no_depende_de_la_infraestructura_ni_lee_el_entorno(capa):
    for f, arbol in _modulos(capa):
        assert not any(m.startswith(("app.infrastructure", "app.main")) for m in _importados(arbol)), f
        for n in ast.walk(arbol):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os":
                assert n.attr not in ("getenv", "environ"), f"{f.relative_to(RAIZ)} lee la configuración del entorno"


def test_el_dominio_no_depende_de_la_aplicacion():
    for f, arbol in _modulos("domain"):
        assert not any(m.startswith("app.application") for m in _importados(arbol)), f


def test_las_capas_viejas_ya_no_existen():
    for vieja in ("api", "services", "data", "models"):
        assert not (RAIZ / vieja).exists()


def _metodos(protocolo) -> set[str]:
    return {n for n, v in vars(protocolo).items() if callable(v) and not n.startswith("_")}


def _adaptadores():
    from app.infrastructure.adapters.outbound.cqrs.consultas import ConsultasCqrs
    from app.infrastructure.adapters.outbound.disco.archivos_vision import ArchivosVisionDisco
    from app.infrastructure.adapters.outbound.dynamo.sagas import AlmacenSagasDynamo
    from app.infrastructure.adapters.outbound.http.clima import ClienteOpenMeteo
    from app.infrastructure.adapters.outbound.http.comedor import ClienteComedorHttp
    from app.infrastructure.adapters.outbound.http.keycloak import ClienteKeycloak
    from app.infrastructure.adapters.outbound.http.mcp_herramientas import McpToolClient
    from app.infrastructure.adapters.outbound.http.n8n import ClienteN8n
    from app.infrastructure.adapters.outbound.http.telegram import ClienteTelegramHttp
    from app.infrastructure.adapters.outbound.s3.objetos import AlmacenS3
    from app.infrastructure.adapters.outbound.sqlite import repositorios as sq
    from app.infrastructure.adapters.outbound.tensorflow.procesador_imagenes import ProcesadorTensorFlow
    return [
        (p_repos.RepositorioPropuestas, sq.RepositorioPropuestasSqlite), (p_repos.RepositorioMensajes, sq.RepositorioMensajesSqlite),
        (p_repos.RepositorioChats, sq.RepositorioChatsSqlite), (p_repos.RepositorioPagosTelegram, sq.RepositorioPagosTelegramSqlite),
        (p_repos.RepositorioVision, sq.RepositorioVisionSqlite), (p_repos.RepositorioDispositivos, sq.RepositorioDispositivosSqlite),
        (p_repos.RepositorioConfig, sq.RepositorioConfigSqlite), (p_repos.RespaldoBaseLocal, sq.RespaldoSqlite),
        (p_sagas.AlmacenSagas, AlmacenSagasDynamo),
        (p_comedor.ServicioMenu, ClienteComedorHttp), (p_comedor.ServicioReservas, ClienteComedorHttp),
        (p_comedor.ServicioPagos, ClienteComedorHttp), (p_comedor.LectorDatosComedor, ClienteComedorHttp),
        (p_externos.HerramientasMcp, McpToolClient), (p_externos.ConsultasLectura, ConsultasCqrs),
        (p_externos.ProveedorIdentidad, ClienteKeycloak), (p_externos.MotorFlujos, ClienteN8n),
        (p_externos.ClienteTelegram, ClienteTelegramHttp), (p_externos.AlmacenObjetos, AlmacenS3),
        (p_externos.ApiClima, ClienteOpenMeteo), (p_externos.ProcesadorImagenes, ProcesadorTensorFlow),
        (p_externos.ArchivosVision, ArchivosVisionDisco),
    ]


@pytest.mark.parametrize("puerto,adaptador", _adaptadores(), ids=lambda x: x.__name__)
def test_cada_adaptador_implementa_todo_su_puerto(puerto, adaptador):
    assert typing.Protocol in puerto.__mro__ or getattr(puerto, "_is_protocol", False)
    faltan = _metodos(puerto) - {n for n, _ in inspect.getmembers(adaptador, callable)}
    assert not faltan, f"{adaptador.__name__} no implementa {faltan} de {puerto.__name__}"
    for nombre in _metodos(puerto):
        esperados = list(inspect.signature(getattr(puerto, nombre)).parameters)
        reales = list(inspect.signature(getattr(adaptador, nombre)).parameters)
        assert reales == esperados, f"{adaptador.__name__}.{nombre}: {reales} != {esperados}"


def test_todos_los_puertos_tienen_adaptador():
    puertos = {c for m in (p_comedor, p_externos, p_repos, p_sagas) for c in vars(m).values()
               if inspect.isclass(c) and getattr(c, "_is_protocol", False) and c.__module__ == m.__name__}
    assert puertos == {p for p, _ in _adaptadores()}
