"""The two ledgers. Both append-only, both integer pence.

An append-only ledger is the whole point: it is the record of what happened,
and what happened does not change. A mistake is corrected by recording
something new. Neither table is ever updated or deleted from, and the first
migration installs triggers that refuse both, so the rule holds even against
a hand-typed statement at the sqlite3 prompt.

Balances are not stored anywhere except on the savings entries themselves,
where each row records the balance after it. That is a running total written
once into an immutable row, not a mutable field that could drift out of step
with the entries that produced it.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, enum_column, utcnow
from app.models.enums import EarningType, SavingsType


class EarningEntry(Base):
    """Money the child has earned. Append-only.

    A settled week writes one entry here for its total. An ad-hoc reward
    writes its own, with the reason in free text. There are no fines and no
    deductions of any kind, so every amount is positive.
    """

    __tablename__ = "earnings_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_type: Mapped[EarningType] = mapped_column(
        enum_column(EarningType), nullable=False
    )
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The week this belongs to. Set for a settlement, and for a reward earned
    #: during a week. Provenance and grouping; never a source of an amount.
    week_id: Mapped[int | None] = mapped_column(ForeignKey("weeks.id", ondelete="RESTRICT"))

    #: The local London day the money was earned on.
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)

    #: Why. Required for a reward — an amount with no reason is unexplainable
    #: three months later, which is when it will be asked about.
    reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    week: Mapped["Week | None"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint("amount_pence >= 0", name="amount_not_negative"),
        CheckConstraint(
            "entry_type <> 'reward' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="a_reward_states_its_reason",
        ),
        CheckConstraint(
            "entry_type <> 'week_settlement' OR week_id IS NOT NULL",
            name="a_settlement_names_its_week",
        ),
    )

    def __repr__(self) -> str:
        return f"<EarningEntry {self.entry_type.value} {self.amount_pence}p>"


class SavingsEntry(Base):
    """A movement in the savings account. Append-only.

    Signed: a withdrawal or a reversal is negative, and those are the only
    two kinds of entry that may be. Neither is a deduction from earnings —
    nothing is ever taken away from the child. A withdrawal is his own money
    leaving his own account by his own choice; a reversal undoes a deposit
    that should not have counted — a reopened week's payment, unwound — and
    is never a correction to an entry that stays exactly as it was written.
    The monthly match needs to see both happen.
    """

    __tablename__ = "savings_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_type: Mapped[SavingsType] = mapped_column(
        enum_column(SavingsType), nullable=False
    )

    #: Signed pence. Negative for a withdrawal, positive or zero otherwise.
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The balance after this entry, written once into a row that cannot be
    #: edited. This is what a parent reconciles against the real account.
    balance_after_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The week whose payday produced this deposit, where there was one.
    week_id: Mapped[int | None] = mapped_column(ForeignKey("weeks.id", ondelete="RESTRICT"))

    #: The local London day the money moved.
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)

    reason: Mapped[str | None] = mapped_column(Text)

    #: Who a standalone deposit was posted by — one of app.config's
    #: parent_names, or the child, chosen at the point of posting. Null for a
    #: deposit split from a payday, which belongs to the week rather than to
    #: a person, and for every other entry type: a match and a reversal are
    #: the scheme's own arithmetic, and an opening balance predates anyone
    #: choosing anything. See app.services.savings_deposits, the only writer
    #: of a standalone deposit.
    posted_by: Mapped[str | None] = mapped_column(String(60))

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    week: Mapped["Week | None"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint(
            "(entry_type IN ('withdrawal', 'reversal') AND amount_pence < 0)"
            " OR (entry_type NOT IN ('withdrawal', 'reversal') AND amount_pence >= 0)",
            name="a_withdrawal_or_reversal_is_negative",
        ),
        CheckConstraint(
            "posted_by IS NULL OR entry_type = 'deposit'",
            name="only_a_deposit_names_who_posted_it",
        ),
        # The account cannot go overdrawn: there is nowhere for the money to
        # come from, and a negative balance would corrupt the monthly low.
        CheckConstraint("balance_after_pence >= 0", name="balance_not_negative"),
    )

    def __repr__(self) -> str:
        return f"<SavingsEntry {self.entry_type.value} {self.amount_pence}p>"
