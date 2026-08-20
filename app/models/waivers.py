"""Waivers: days away, and chores excused for a week.

A waiver does not forgive a miss. It means no assessable instance existed in
the first place, which is a different thing and produces different figures: a
weekly count scales down by the days waived rather than being failed.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, enum_column, utcnow
from app.models.enums import WaiverScope


class Waiver(Base):
    """Either a whole day, or one chore for one week.

    The two scopes share a table because they are the same act — a parent
    saying "this is not assessed" — and the CHECK below keeps each shape
    honest about which columns it is allowed to fill in.
    """

    __tablename__ = "waivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[WaiverScope] = mapped_column(enum_column(WaiverScope), nullable=False)

    #: The local London day waived, for a DAY waiver.
    day: Mapped[date | None] = mapped_column(Date)

    #: The week and chore excused, for a CHORE_WEEK waiver.
    week_id: Mapped[int | None] = mapped_column(ForeignKey("weeks.id", ondelete="RESTRICT"))
    definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("chore_definitions.id", ondelete="RESTRICT")
    )

    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    week: Mapped["Week | None"] = relationship()  # noqa: F821
    definition: Mapped["ChoreDefinition | None"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint(
            "(scope = 'day' AND day IS NOT NULL"
            "   AND definition_id IS NULL)"
            " OR (scope = 'chore_week' AND day IS NULL"
            "   AND week_id IS NOT NULL AND definition_id IS NOT NULL)",
            name="each_scope_fills_in_its_own_columns",
        ),
        Index("uq_waivers_day", "day", unique=True, sqlite_where=day.isnot(None)),
        Index(
            "uq_waivers_chore_week",
            "week_id",
            "definition_id",
            unique=True,
            sqlite_where=day.is_(None),
        ),
    )

    def __repr__(self) -> str:
        if self.scope is WaiverScope.DAY:
            return f"<Waiver day {self.day}>"
        return f"<Waiver chore {self.definition_id} week {self.week_id}>"
