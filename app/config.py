"""Configuration, read from the environment.

CHILD_NAME and PARENT_PIN have no defaults: the child is configuration, not
code, and a PIN that falls back to something is not a PIN. Both must be
supplied at deployment or the service refuses to start.
"""

from __future__ import annotations

import os
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when a required environment variable is absent, empty or invalid."""


def _get(name: str, default: str | None = None) -> str:
    """An unset variable and one set to empty are the same thing."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if default is None:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return default


class Settings:
    """Runtime configuration for one deployment of the service."""

    def __init__(self) -> None:
        self.child_name: str = _get("CHILD_NAME")
        self.parent_pin: str = _get("PARENT_PIN")
        self.database_url: str = _get("DATABASE_URL", "sqlite:///./coinquest.db")

        port = _get("COINQUEST_PORT", "8600")
        if not port.isdigit():
            raise ConfigError(f"COINQUEST_PORT must be a number, got {port!r}.")
        self.port: int = int(port)

        # The container clock is UTC. Every week boundary, payday and monthly
        # period is computed in this zone, set explicitly rather than inherited.
        # Resolved here so a bad zone fails at startup, not mid-settlement.
        self.timezone: str = _get("TZ", "Europe/London")
        try:
            self.tzinfo: ZoneInfo = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"TZ is not a known timezone: {self.timezone!r}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
