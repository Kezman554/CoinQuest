"""The scheme-wide settings a parent can change without a redeploy.

One row. Unlike app.config.Settings (an env var read once at process start,
requiring a restart to change), this table holds figures reviewed and edited
through the app itself — currently the one figure the scheme needs like
this. Nothing here is per-week or per-chore; that is what ChoreDefinition and
the ledgers are for.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UtcDateTime, utcnow


class SchemeSettings(Base):
    """The scheme's own dials. Exactly one row, seeded by its migration.

    Nothing here ever inserts a second row — every reader assumes precisely
    one exists, the way a household has exactly one scheme.
    """

    __tablename__ = "scheme_settings"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: What the basic chores are collectively worth for the week, all or
    #: nothing — see recovery.WeekAssessment.chore_pay_at_stake_pence. Not a
    #: sum of the individual basic chores' own amounts: they carry none any
    #: more, and exist only to gate whether this pot pays out. A different
    #: figure from app.config.Settings.weekly_base_pence, which is the
    #: unconditional allowance and is not this.
    weekly_basic_pay_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("weekly_basic_pay_pence >= 0", name="weekly_basic_pay_not_negative"),
    )

    def __repr__(self) -> str:
        return f"<SchemeSettings weekly_basic_pay_pence={self.weekly_basic_pay_pence}>"
