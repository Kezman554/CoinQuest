"""Test environment. The real .env is never relied on: tests supply their own."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("CHILD_NAME", "Test Child")
os.environ.setdefault("PARENT_PIN", "0000")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test-coinquest.db")
os.environ.setdefault("COINQUEST_PORT", "8600")
os.environ.setdefault("TZ", "Europe/London")


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
