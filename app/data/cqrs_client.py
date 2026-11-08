"""Cliente de la base de lectura CQRS (PostgreSQL). Solo-lectura."""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _engine() -> Engine:
    url = os.getenv("CQRS_DATABASE_URL", "postgresql://cqrs:cqrs123@postgres-cqrs:5432/cqrs_read")
    return create_engine(url, pool_pre_ping=True)


_engine_singleton: Engine | None = None


def engine() -> Engine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = _engine()
    return _engine_singleton


def run_query_predefinida(nombre: str, params: dict) -> list[dict]:
    """SPEC §10: solo consultas predefinidas y parametrizadas."""
    queries = {
        "raciones_por_dia": "SELECT fecha, SUM(cantidad) AS total FROM raciones_vw WHERE fecha BETWEEN :desde AND :hasta GROUP BY fecha ORDER BY fecha",
        "desperdicio_por_plato": "SELECT plato_id, AVG(pct_desperdicio) AS pct FROM desperdicio_vw WHERE fecha BETWEEN :desde AND :hasta GROUP BY plato_id",
        "becarios_inactivos": "SELECT estudiante_id FROM beca_uso_vw WHERE ultima_racion < :desde",
    }
    sql = queries.get(nombre)
    if not sql:
        raise ValueError(f"Query predefinida no existe: {nombre}")
    try:
        with engine().connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        # dev local: BD puede no tener aún las vistas
        return []
