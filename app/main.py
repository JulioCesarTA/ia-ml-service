"""ia-ml-service — FastAPI app con Arquitectura Hexagonal (puertos y adaptadores).

Este módulo es la raíz de composición: lee la configuración del entorno, crea los adaptadores de salida
(SQLite, DynamoDB, HTTP, Keycloak, n8n, Telegram, S3, clima, CQRS, TensorFlow), los inyecta en los casos de uso
(app.application) y monta los adaptadores de entrada (routers HTTP, sondeo de Telegram y relojes).

    domain  <-  application (+ ports)  <-  infrastructure (adapters)  <-  main
"""
import os
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.application.agentes.agentes import InventarioComprasAgent, MonitorComedorAgent, PlanificadorMenuAgent
from app.application.agentes.avisos import ServicioAvisos
from app.application.agentes.paquete_offline import PaqueteOffline
from app.application.analitica.agrupamiento import ServicioAgrupamiento
from app.application.analitica.clima import ServicioClima
from app.application.analitica.datos import DatosMenus
from app.application.analitica.kpis import ServicioKpis
from app.application.analitica.regresion import ServicioRegresion
from app.application.analitica.vision import ServicioVision
from app.application.asistente import Asistente
from app.application.cola_mensajes import ColaMensajes
from app.application.identidad import ServicioIdentidad
from app.application.programador import Programador
from app.application.propuestas import ServicioPropuestas
from app.application.push import ServicioPush
from app.application.reportes.fuentes import FuentesReportes
from app.application.reportes.snapshot import ServicioSnapshot
from app.application.respaldo import ServicioRespaldo
from app.application.saga.orquestador import SagaOrchestrator
from app.application.telegram_bot import ServicioTelegram
from app.domain.propuestas import VENTANA_S_DEFECTO
from app.infrastructure.adapters.inbound.http import agentes as http_agentes
from app.infrastructure.adapters.inbound.http import predicciones as http_predicciones
from app.infrastructure.adapters.inbound.http import push as http_push
from app.infrastructure.adapters.inbound.http import reportes as http_reportes
from app.infrastructure.adapters.inbound.http import sagas as http_sagas
from app.infrastructure.adapters.inbound.tareas import relojes
from app.infrastructure.adapters.inbound.telegram import sondeo
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
from app.infrastructure.adapters.outbound.sqlite.base import BaseLocal, directorio_datos
from app.infrastructure.adapters.outbound.sqlite.repositorios import (
    RepositorioChatsSqlite, RepositorioConfigSqlite, RepositorioDispositivosSqlite, RepositorioMensajesSqlite,
    RepositorioPagosTelegramSqlite, RepositorioPropuestasSqlite, RepositorioVisionSqlite, RespaldoSqlite)
from app.infrastructure.adapters.outbound.tensorflow.procesador_imagenes import ProcesadorTensorFlow


@dataclass
class Configuracion:
    """Todo lo que se lee del entorno para los casos de uso (los adaptadores leen sus propias variables)."""
    directorio_datos: str
    ventana_avisos_s: int
    telegram_recepcion_n8n: bool
    vigilancia: bool
    vigilancia_inicio_s: int

    @staticmethod
    def del_entorno() -> "Configuracion":
        return Configuracion(
            directorio_datos=directorio_datos(),
            ventana_avisos_s=int(os.getenv("AVISO_VENTANA_S", str(VENTANA_S_DEFECTO))),
            telegram_recepcion_n8n=os.getenv("TELEGRAM_RECEPCION", "interna").lower() == "n8n",
            vigilancia=os.getenv("VIGILANCIA", "on") == "on",
            vigilancia_inicio_s=int(os.getenv("VIGILANCIA_INICIO_S", "45")),
        )


def _stripe_de_prueba() -> bool:
    return os.getenv("STRIPE_SECRET_KEY", "").startswith("sk_test")


@dataclass
class Contenedor:
    config: Configuracion
    # adaptadores de salida
    base: BaseLocal
    comedor: ClienteComedorHttp
    mcp: McpToolClient
    n8n: ClienteN8n
    s3: AlmacenS3
    repo_propuestas: RepositorioPropuestasSqlite
    repo_dispositivos: RepositorioDispositivosSqlite
    repo_vision: RepositorioVisionSqlite
    repo_config: RepositorioConfigSqlite
    # casos de uso
    cola: ColaMensajes
    identidad: ServicioIdentidad
    propuestas: ServicioPropuestas
    push: ServicioPush
    avisos: ServicioAvisos
    telegram: ServicioTelegram
    asistente: Asistente
    datos: DatosMenus
    clima: ServicioClima
    regresion: ServicioRegresion
    vision: ServicioVision
    agrupamiento: ServicioAgrupamiento
    fuentes: FuentesReportes
    kpis: ServicioKpis
    snapshot: ServicioSnapshot
    inventario_agente: InventarioComprasAgent
    planificador_agente: PlanificadorMenuAgent
    monitor_agente: MonitorComedorAgent
    paquete_offline: PaqueteOffline
    programador: Programador
    respaldo: ServicioRespaldo

    def nueva_saga(self) -> SagaOrchestrator:
        return SagaOrchestrator(self.comedor, self.comedor, self.comedor, AlmacenSagasDynamo())


def construir(config: Configuracion | None = None) -> Contenedor:
    config = config or Configuracion.del_entorno()

    # ---- adaptadores de salida
    base = BaseLocal(config.directorio_datos)
    comedor = ClienteComedorHttp()
    mcp = McpToolClient()
    n8n = ClienteN8n()
    s3 = AlmacenS3()
    consultas = ConsultasCqrs()
    repo_propuestas = RepositorioPropuestasSqlite(base)
    repo_dispositivos = RepositorioDispositivosSqlite(base)
    repo_vision = RepositorioVisionSqlite(base)
    repo_config = RepositorioConfigSqlite(base)

    # ---- casos de uso
    cola = ColaMensajes(RepositorioMensajesSqlite(base))
    identidad = ServicioIdentidad(ClienteKeycloak(), comedor, RepositorioChatsSqlite(base))
    propuestas = ServicioPropuestas(repo_propuestas, mcp, n8n, cola, config.ventana_avisos_s)
    push = ServicioPush(repo_dispositivos, n8n)
    avisos = ServicioAvisos(propuestas, push, cola)
    telegram = ServicioTelegram(ClienteTelegramHttp(n8n), cola, identidad, propuestas, repo_config)

    datos = DatosMenus(comedor)
    clima = ServicioClima(ClienteOpenMeteo(), repo_config)
    regresion = ServicioRegresion(datos, clima)
    vision = ServicioVision(repo_vision, ArchivosVisionDisco(config.directorio_datos), s3, ProcesadorTensorFlow())
    agrupamiento = ServicioAgrupamiento(datos, vision.desperdicio_medio_por_plato)
    fuentes = FuentesReportes(comedor, repo_vision, datos)

    inventario_agente = InventarioComprasAgent(mcp)
    planificador_agente = PlanificadorMenuAgent(mcp, regresion.predecir_demanda)
    monitor_agente = MonitorComedorAgent(consultas, mcp)

    c = Contenedor(
        config=config, base=base, comedor=comedor, mcp=mcp, n8n=n8n, s3=s3,
        repo_propuestas=repo_propuestas, repo_dispositivos=repo_dispositivos, repo_vision=repo_vision, repo_config=repo_config,
        cola=cola, identidad=identidad, propuestas=propuestas, push=push, avisos=avisos, telegram=telegram, asistente=None,
        datos=datos, clima=clima, regresion=regresion, vision=vision, agrupamiento=agrupamiento, fuentes=fuentes,
        kpis=ServicioKpis(fuentes), snapshot=ServicioSnapshot(fuentes),
        inventario_agente=inventario_agente, planificador_agente=planificador_agente, monitor_agente=monitor_agente,
        paquete_offline=PaqueteOffline(consultas, mcp, regresion.predecir_demanda),
        programador=Programador(repo_config, avisos, inventario_agente, planificador_agente, monitor_agente),
        respaldo=ServicioRespaldo(RespaldoSqlite(base), s3),
    )
    c.asistente = Asistente(telegram, identidad, propuestas, c.nueva_saga, mcp, comedor,
                            RepositorioPagosTelegramSqlite(base), _stripe_de_prueba)
    telegram.asistente = c.asistente
    return c


def crear_app(c: Contenedor) -> FastAPI:
    api = FastAPI(title="ia-ml-service", version="1.0.0",
                  description="Comedor UAGRM — IA/ML + Agentes + Saga orchestrator")

    api.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    @api.on_event("startup")
    def _arrancar_vigilancia() -> None:
        sondeo.iniciar(c.telegram, c.asistente, c.config.telegram_recepcion_n8n)
        relojes.iniciar_programador(c.programador, c.config.vigilancia, c.config.vigilancia_inicio_s)
        relojes.iniciar_respaldo(c.respaldo)
        relojes.precargar_cnn(c.vision)

    @api.get("/health")
    def health() -> dict:
        return {"status": "UP", "service": "ia-ml-service"}

    api.include_router(http_predicciones.crear_router(c.regresion, c.datos, c.fuentes, c.clima, c.agrupamiento, c.kpis, c.vision),
                       prefix="/ml", tags=["ml"])
    api.include_router(http_agentes.crear_router(c.inventario_agente, c.planificador_agente, c.monitor_agente, c.avisos,
                                                 c.propuestas, c.telegram, c.paquete_offline, c.programador),
                       prefix="/agentes", tags=["agentes"])
    api.include_router(http_reportes.crear_router(c.snapshot), prefix="/reportes", tags=["reportes"])
    api.include_router(http_sagas.crear_router(c.nueva_saga), prefix="/sagas", tags=["sagas"])
    # bajo /agentes para que el gateway ya lo enrute: las notificaciones son un canal más de los agentes
    api.include_router(http_push.crear_router(c.push), prefix="/agentes/push", tags=["push"])
    return api


contenedor = construir()
app = crear_app(contenedor)
