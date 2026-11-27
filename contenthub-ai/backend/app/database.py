from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


@dataclass(frozen=True)
class DatabaseDiagnostic:
    connected: bool
    status: str
    database_name: str
    host: str
    port: int
    user: str
    uses_root_user: bool
    server_version: str | None
    character_set: str | None
    innodb_available: bool | None
    latency_ms: float | None
    pool_size: int
    max_overflow: int
    pool_recycle: int
    error: str | None = None


def create_mysql_engine(
    settings: Settings | None = None, url_override: str | None = None
) -> Engine:
    """Create a conservatively pooled SQLAlchemy engine for MySQL via PyMySQL."""
    cfg = settings or get_settings()
    target_url = url_override or cfg.database_url
    if not target_url.startswith("mysql+pymysql://"):
        raise ValueError("Only mysql+pymysql:// URLs are permitted by ContentHub AI.")

    return create_engine(
        target_url,
        pool_size=cfg.db_pool_size,
        max_overflow=cfg.db_max_overflow,
        pool_recycle=cfg.db_pool_recycle,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": cfg.db_connect_timeout,
            "charset": "utf8mb4",
        },
        future=True,
    )


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_mysql_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _session_factory


def reset_engine() -> None:
    """Dispose the cached engine (used during shutdown or test reconfiguration)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def check_database_connection(
    settings: Settings | None = None,
    engine: Engine | None = None,
) -> DatabaseDiagnostic:
    """Probe MySQL connectivity, version, InnoDB support, and utf8mb4 charset safely."""
    cfg = settings or get_settings()
    target_engine = engine or get_engine()
    started = time.perf_counter()

    try:
        with target_engine.connect() as conn:
            version_row = conn.execute(text("SELECT VERSION()")).scalar()
            charset_row = conn.execute(text("SELECT @@character_set_database")).scalar()
            engines_rows: list[Any] = list(conn.execute(text("SHOW ENGINES")).fetchall())
            innodb_ok = any(
                str(row[0]).lower() == "innodb" and str(row[1]).upper() in {"YES", "DEFAULT"}
                for row in engines_rows
            )

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return DatabaseDiagnostic(
            connected=True,
            status="ok",
            database_name=cfg.db_name,
            host=cfg.db_host,
            port=cfg.db_port,
            user=cfg.db_user,
            uses_root_user=cfg.is_root_db_user,
            server_version=str(version_row) if version_row is not None else None,
            character_set=str(charset_row) if charset_row is not None else None,
            innodb_available=innodb_ok,
            latency_ms=latency_ms,
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
            pool_recycle=cfg.db_pool_recycle,
            error=None,
        )
    except SQLAlchemyError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return DatabaseDiagnostic(
            connected=False,
            status="unavailable",
            database_name=cfg.db_name,
            host=cfg.db_host,
            port=cfg.db_port,
            user=cfg.db_user,
            uses_root_user=cfg.is_root_db_user,
            server_version=None,
            character_set=None,
            innodb_available=None,
            latency_ms=latency_ms,
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
            pool_recycle=cfg.db_pool_recycle,
            error=f"{type(exc).__name__}: unable to connect to configured MySQL database.",
        )
