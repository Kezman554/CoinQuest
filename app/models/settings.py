"""The scheme-wide settings a parent can change without a redeploy.

One row. Unlike app.config.Settings (an env var read once at process start,
requiring a restart to change), this table holds figures reviewed and edited
through the app itself. Nothing here is per-week or per-chore; that is what
ChoreDefinition and the ledgers are for.
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

    #: Where the monthly savings-match ladder starts, in whole percent — the
    #: rate a clean first month, or a month straight after a withdrawal,
    #: earns. See app.services.savings_match for the ladder itself; this and
    #: the two settings below are only its tunable ends, reviewed at whatever
    #: cadence a household reviews pocket money at all.
    savings_match_start_rate_percent: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Where the ladder stops climbing, in whole percent. A run of consecutive
    #: clean months rises one point at a time and holds here.
    savings_match_ceiling_rate_percent: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The matched portion of a month's low tops out here. A rate ceiling, not
    #: a stop: a balance past this figure keeps earning the match, just on no
    #: more than this much of itself. See savings_match._match_pence.
    savings_match_cap_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint("weekly_basic_pay_pence >= 0", name="weekly_basic_pay_not_negative"),
        CheckConstraint(
            "savings_match_start_rate_percent >= 0"
            " AND savings_match_start_rate_percent <= savings_match_ceiling_rate_percent",
            name="savings_match_start_rate_within_range",
        ),
        CheckConstraint(
            "savings_match_ceiling_rate_percent <= 100",
            name="savings_match_ceiling_rate_at_most_100",
        ),
        CheckConstraint(
            "savings_match_cap_pence >= 0", name="savings_match_cap_not_negative"
        ),
    )

    def __repr__(self) -> str:
        return f"<SchemeSettings weekly_basic_pay_pence={self.weekly_basic_pay_pence}>"
