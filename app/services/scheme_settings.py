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
