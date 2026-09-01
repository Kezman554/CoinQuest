"""Test environment. The real .env is never relied on: tests supply their own."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("CHILD_NAME", "Test Child")
os.environ.setdefault("PARENT_PIN", "0000")
os.environ.setdefault("PARENT_NAMES", "Test Parent")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test-coinquest.db")
os.environ.setdefault("COINQUEST_PORT", "8600")
os.environ.setdefault("TZ", "Europe/London")

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh_limiter():
    """A clean attempt limiter per test.

    The limiter is process-global by design — it is the one thing in this
    service that has to remember something between requests. Tests that send a
    wrong PIN would otherwise leave a cooling-off in place for every test
    after them.
    """
    from app.services.lockout import reset_limiter

    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture()
def migrated_database(tmp_path, monkeypatch):
    """An empty file, brought up to head by the real Alembic migration.

    Not Base.metadata.create_all: that would test the models against
    themselves and never once run the migration that the Pi will actually
    execute. The triggers in particular exist only in the migration.
    """
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{(tmp_path / 'coinquest.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)

    from app.config import get_settings

    get_settings.cache_clear()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "migrations"))
    command.upgrade(config, "head")

    yield url

    get_settings.cache_clear()


@pytest.fixture()
def session(migrated_database):
    """A session against a freshly migrated database."""
    from sqlalchemy.orm import Session

    from app.db import create_app_engine

    engine = create_app_engine(migrated_database)
    with Session(engine, future=True) as session:
        yield session
    engine.dispose()
