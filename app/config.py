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

        # The base allowance: paid every week regardless of how the chores
        # went, and removed only by a week being voided. A separate figure
        # from the chore pay, which is earned and can be lost.
        base = _get("WEEKLY_BASE_PENCE", "100")
        if not base.isdigit():
            raise ConfigError(f"WEEKLY_BASE_PENCE must be whole pence, got {base!r}.")
        self.weekly_base_pence: int = int(base)

        # How many consecutive wrong PINs a source gets, and how long it is
        # then refused for. A four-digit PIN typed in front of a child is
        # guessable by anything that can reach the port; this is what stands
        # in the way.
        limit = _get("PIN_ATTEMPT_LIMIT", "5")
        if not limit.isdigit() or int(limit) < 1:
            raise ConfigError(f"PIN_ATTEMPT_LIMIT must be at least 1, got {limit!r}.")
        self.pin_attempt_limit: int = int(limit)

        cool_off = _get("PIN_COOL_OFF_SECONDS", "300")
        if not cool_off.isdigit() or int(cool_off) < 1:
            raise ConfigError(
                f"PIN_COOL_OFF_SECONDS must be at least 1, got {cool_off!r}."
            )
        self.pin_cool_off_seconds: int = int(cool_off)

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
