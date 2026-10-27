"""Configuration, read from the environment.

CHILD_NAME and the parents have no defaults: the people are configuration,
not code — no name appears in this repository — and a PIN that falls back to
something is not a PIN. They must be supplied at deployment or the service
refuses to start.

The parents are numbered pairs, PARENT_1_NAME / PARENT_1_PIN, PARENT_2_NAME /
PARENT_2_PIN and so on, and a PIN proves which of them is acting (see
app.services.authorisation). BANK_HOLDER names the one who pays the savings
match into the bank — the only act restricted to one parent.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
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


#: Every column a parent's name is recorded in is this long (String(60)).
NAME_LIMIT = 60

#: Replaced by the numbered parents. Refused rather than ignored if still
#: set, so an old PIN cannot sit unnoticed in the environment.
RETIRED = ("PARENT_PIN", "PARENT_NAMES")

_PARENT_VARIABLE = re.compile(r"^PARENT_(\d+)_(NAME|PIN)$")


@dataclass(frozen=True)
class Parent:
    """One configured parent: the number they are configured under, the name
    recorded against what they authorise, and the PIN that proves it."""

    number: int
    name: str
    pin: str


def _parents() -> tuple[Parent, ...]:
    """Every PARENT_n_NAME / PARENT_n_PIN pair, in number order.

    A pair with both halves empty is not a parent: a compose file passes
    PARENT_2_NAME / PARENT_2_PIN through whether or not there is a second
    parent, and empty is how it says there is not. Refuses a half-configured
    pair (one half empty), a name too long to record, two parents with the
    same name (the record could not tell them apart) or the same PIN (a PIN
    would not prove which one is acting), and no parents at all.
    """
    numbers = sorted(
        {
            int(match.group(1))
            for key, value in os.environ.items()
            if (match := _PARENT_VARIABLE.match(key)) and value.strip()
        }
    )
    parents = []
    for number in numbers:
        name = _get(f"PARENT_{number}_NAME")
        pin = _get(f"PARENT_{number}_PIN")
        if len(name) > NAME_LIMIT:
            raise ConfigError(f"PARENT_{number}_NAME is longer than {NAME_LIMIT} characters.")
        parents.append(Parent(number=number, name=name, pin=pin))

    if not parents:
        raise ConfigError(
            "No parent is configured. Set PARENT_1_NAME and PARENT_1_PIN"
            " (and PARENT_2_NAME / PARENT_2_PIN for a second)."
        )
    if len({parent.pin for parent in parents}) != len(parents):
        raise ConfigError("Two parents share a PIN; each PIN must prove one parent.")
    if len({parent.name for parent in parents}) != len(parents):
        raise ConfigError("Two parents share a name; the record could not tell them apart.")
    return tuple(parents)


class Settings:
    """Runtime configuration for one deployment of the service."""

    def __init__(self) -> None:
        self.child_name: str = _get("CHILD_NAME")

        for name in RETIRED:
            if os.environ.get(name, "").strip():
                raise ConfigError(
                    f"{name} is no longer read: parents are PARENT_1_NAME / PARENT_1_PIN,"
                    f" PARENT_2_NAME / PARENT_2_PIN, with BANK_HOLDER. Remove {name}."
                )

        self.parents: tuple[Parent, ...] = _parents()

        # The parent who pays the savings match into the bank, by number.
        holder = _get("BANK_HOLDER")
        found = [parent for parent in self.parents if str(parent.number) == holder]
        if not found:
            raise ConfigError(
                f"BANK_HOLDER must be the number of a configured parent"
                f" ({', '.join(str(parent.number) for parent in self.parents)}), got {holder!r}."
            )
        self.bank_holder: Parent = found[0]

        # Who may post a savings deposit directly: the configured parents, by
        # name. See app.services.savings_deposits, the one place that reads it.
        self.parent_names: list[str] = [parent.name for parent in self.parents]

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

        # The cooling-off starts here and doubles with each consecutive
        # lockout, up to the cap. Short to begin with because the kitchen
        # screen is shared: the usual cause is a mistype, not an attack.
        start = _get("PIN_COOL_OFF_START_SECONDS", "30")
        if not start.isdigit() or int(start) < 1:
            raise ConfigError(
                f"PIN_COOL_OFF_START_SECONDS must be at least 1, got {start!r}."
            )
        self.pin_cool_off_start_seconds: int = int(start)

        ceiling = _get("PIN_COOL_OFF_MAX_SECONDS", "900")
        if not ceiling.isdigit() or int(ceiling) < int(start):
            raise ConfigError(
                f"PIN_COOL_OFF_MAX_SECONDS must be at least the starting"
                f" cooling-off ({start}), got {ceiling!r}."
            )
        self.pin_cool_off_max_seconds: int = int(ceiling)

        port = _get("COINQUEST_PORT", "8600")
        if not port.isdigit():
            raise ConfigError(f"COINQUEST_PORT must be a number, got {port!r}.")
        self.port: int = int(port)

        # The built React bundle, served at / when present (see app.frontend).
        # Absent in dev and in the test suite, where Vite serves the app and
        # the dev proxy stands in for same-origin. The Dockerfile points this
        # at the bundle it builds; resolved to absolute so it is stable
        # whatever the process's working directory turns out to be.
        self.frontend_dir: Path = Path(_get("FRONTEND_DIR", "frontend/dist")).resolve()

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
