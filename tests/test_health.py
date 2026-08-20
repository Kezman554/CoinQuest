"""The health endpoint, and the configuration it depends on."""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_the_london_timezone(client):
    # The container clock is UTC; the week boundary depends on this being set.
    assert client.get("/health").json()["timezone"] == "Europe/London"


@pytest.mark.parametrize("name", ["CHILD_NAME", "PARENT_PIN"])
def test_required_settings_have_no_default(monkeypatch, name):
    monkeypatch.setenv("CHILD_NAME", "Test Child")
    monkeypatch.setenv("PARENT_PIN", "0000")
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfigError):
        Settings()


def test_optional_settings_fall_back(monkeypatch):
    monkeypatch.setenv("CHILD_NAME", "Test Child")
    monkeypatch.setenv("PARENT_PIN", "0000")
    monkeypatch.delenv("COINQUEST_PORT", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    settings = Settings()
    assert settings.port == 8600
    assert settings.timezone == "Europe/London"


def test_a_blank_optional_setting_is_treated_as_unset(monkeypatch):
    # .env.example ships these commented shapes; a blank line must not crash.
    monkeypatch.setenv("CHILD_NAME", "Test Child")
    monkeypatch.setenv("PARENT_PIN", "0000")
    monkeypatch.setenv("COINQUEST_PORT", "")
    monkeypatch.setenv("TZ", "")
    settings = Settings()
    assert settings.port == 8600
    assert settings.timezone == "Europe/London"


def test_an_unknown_timezone_is_rejected_at_startup(monkeypatch):
    monkeypatch.setenv("CHILD_NAME", "Test Child")
    monkeypatch.setenv("PARENT_PIN", "0000")
    monkeypatch.setenv("TZ", "Europe/Nowhere")
    with pytest.raises(ConfigError):
        Settings()
