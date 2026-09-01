"""Reading and writing the scheme's own settings — currently one figure.

Named apart from app.config.get_settings() deliberately: that is env-var
configuration, read once at process start and needing a restart to change.
This is reviewed and edited through the app itself, the same way a chore
definition is, and lives in the database for exactly that reason.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.settings import SchemeSettings


def get_row(session: Session) -> SchemeSettings:
    """The one row. Seeded by its migration; nothing here ever creates a second."""
    row = session.query(SchemeSettings).first()
    if row is None:
        raise RuntimeError(
            "No scheme_settings row — the migration that seeds one has not run."
        )
    return row


def weekly_basic_pay_pence(session: Session) -> int:
    """What the basic chores are collectively worth this week, all or nothing."""
    return get_row(session).weekly_basic_pay_pence


def savings_match_start_rate_percent(session: Session) -> int:
    """The rate a clean first month, or the month straight after a
    withdrawal, earns. See app.services.savings_match."""
    return get_row(session).savings_match_start_rate_percent


def savings_match_ceiling_rate_percent(session: Session) -> int:
    """Where the savings-match ladder stops climbing."""
    return get_row(session).savings_match_ceiling_rate_percent


def savings_match_cap_pence(session: Session) -> int:
    """The matched portion of a month's low tops out here."""
    return get_row(session).savings_match_cap_pence
