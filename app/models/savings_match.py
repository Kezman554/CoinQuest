"""The monthly savings match, settled. One row per calendar month, ever.

The weekly ledger's shape, applied to a month: `SavingsMonthMatch` stores the
figures a settled month paid on — the balance low it matched, the rate the
ladder was on, the cap in force, and what that came to — rather than a
pointer back to today's scheme_settings. A parent reviewing the ladder next
June must never change what last April paid; storing the figures rather than
recomputing them from the current settings is what makes that true. See
app.services.settlement for the same argument made about weeks, and
app.services.savings_match for the ladder itself.

The first migration this table appears in also gives it the same immutability
triggers as the other closed-event tables: a row here is never updated or
deleted, not even by a hand-typed statement at the sqlite3 prompt.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UtcDateTime, utcnow


class SavingsMonthMatch(Base):
    """One calendar month's savings match, closed forever.

    `balance_low_pence` is the figure the ladder actually matched on — the
    lowest the account reached that month, or, in a month a withdrawal
    happened, the lowest it reached *after* that withdrawal. `had_withdrawal`
    records which of those this was, which is also what resets the ladder for
    the month after. `rate_percent` and `cap_pence` are the ladder's state and
    the scheme's cap as they stood the moment this month settled — not looked
    up from scheme_settings today, for the same reason a settled week never
    rereads a chore definition.
    """

    __tablename__ = "savings_month_matches"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: The calendar month, first day to last — half-open in the same sense
    #: every other Period in this app is; see app.services.calendar.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    balance_low_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    had_withdrawal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rate_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    cap_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    match_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Provenance only, pointing at the savings_ledger row this settlement
    #: appended — never read to work out money. Set even for a nil match: a
    #: month that matched nothing still closes on that figure, recorded
    #: exactly the way a non-zero one is.
    match_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("savings_ledger.id", ondelete="RESTRICT")
    )

    settled_by: Mapped[str] = mapped_column(String(60), nullable=False)
    settled_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("period_start", name="one_settlement_per_month"),
        CheckConstraint(
            "strftime('%d', period_start) = '01'", name="period_start_is_the_first_of_the_month"
        ),
        CheckConstraint(
            "date(period_end, '+1 day') = date(period_start, '+1 month')",
            name="period_end_is_the_last_of_the_same_month",
        ),
        CheckConstraint("balance_low_pence >= 0", name="balance_low_not_negative"),
        CheckConstraint(
            "rate_percent >= 0 AND rate_percent <= 100", name="rate_between_0_and_100"
        ),
        CheckConstraint("cap_pence >= 0", name="cap_not_negative"),
        CheckConstraint("match_pence >= 0", name="match_not_negative"),
        # The formula itself, not just its inputs: a match this row disagrees
        # with about its own arithmetic is refused by the database, not only
        # by whatever service code happened to compute it.
        CheckConstraint(
            "match_pence = (MIN(balance_low_pence, cap_pence) * rate_percent + 50) / 100",
            name="match_is_the_rate_applied_to_the_capped_low",
        ),
    )

    def __repr__(self) -> str:
        return f"<SavingsMonthMatch {self.period_start.isoformat()} {self.match_pence}p>"
