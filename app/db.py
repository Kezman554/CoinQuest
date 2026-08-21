"""Engine and session handling.

SQLite needs two things saying to it explicitly on every connection. Foreign
keys are off by default, which would quietly turn every ON DELETE RESTRICT in
the schema into nothing at all. And the default journal is slower and less
crash-safe than WAL on a Pi that may lose power.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record) -> None:
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_app_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, future=True)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_app_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), future=True)
    return _session_factory


def run_migrations() -> None:
    """Bring the database up to head.

    Alembic owns the schema; nothing here ever calls create_all, because the
    append-only triggers exist only in the migrations. Run at startup so the
    deploy story stays "git pull && docker compose up" — a migration cannot
    be forgotten, because bringing the app up is what applies it. Idempotent:
    a database already at head is a no-op.
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    # Absolute, so it resolves whatever the process's working directory turns
    # out to be — the container's differs from a laptop's.
    config.set_main_option("script_location", str(PROJECT_ROOT / "app" / "migrations"))
    command.upgrade(config, "head")


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
