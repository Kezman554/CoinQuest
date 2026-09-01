"""A savings deposit Oliver submits himself, waiting on a parent.

Not the savings ledger, and deliberately not append-only the way that is:
this row is a proposal, and a proposal is exactly the thing this scheme
already lets move between states before it becomes money — the same shape
ChoreInstance's claimed/confirmed already is. It is created pending, and
ends either confirmed (a real SavingsEntry now exists, linked back by
savings_entry_id) or rejected (the ledger never hears about it). Neither
ending is itself undone; a parent who confirmed in error records a
withdrawal, the same as any other correction to a real ledger entry, never
an edit here.

A parent posting a deposit directly never creates one of these at all —
see app.services.savings_deposits.record_parent_deposit, which writes
straight to the ledger. This table exists only for the half of the flow
that has to wait.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, enum_column, utcnow
from app.models.enums import DepositRequestState


class PendingSavingsDeposit(Base):
    """One deposit Oliver has proposed, not yet ruled on or ruled on already."""

    __tablename__ = "savings_deposit_requests"

    id: Mapped[int] = mapped_column(primary_key=True)

    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)

    #: Always the child's name today — this endpoint refuses anything else,
    #: see app.services.savings_deposits — stored anyway rather than assumed,
    #: the same reason ChoreInstance.authorised_by is stored although there is
    #: one parent: the day a second submitter exists, the history already
    #: says which one this was.
    posted_by: Mapped[str] = mapped_column(String(60), nullable=False)

    #: The local London day the money arrived, chosen at submission and
    #: carried unchanged into the ledger entry a confirm writes.
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)

    state: Mapped[DepositRequestState] = mapped_column(
        enum_column(DepositRequestState),
        nullable=False,
        default=DepositRequestState.PENDING,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    #: Who confirmed or rejected this — the PIN's own party, the same value
    #: ChoreInstance.authorised_by and SavingsMonthMatch.settled_by record.
    decided_by: Mapped[str | None] = mapped_column(String(60))

    #: Set only on confirm, to the entry it created. Restricted rather than
    #: cascaded: the ledger entry this points to is append-only and outlives
    #: everything, so nothing may delete it out from under this row either.
    savings_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("savings_ledger.id", ondelete="RESTRICT")
    )

    entry: Mapped["SavingsEntry | None"] = relationship()  # noqa: F821

    __table_args__ = (
        CheckConstraint("amount_pence > 0", name="amount_positive"),
        CheckConstraint("length(trim(note)) > 0", name="a_deposit_states_its_note"),
        CheckConstraint(
            "(state = 'pending') = (decided_at IS NULL AND decided_by IS NULL)",
            name="a_decision_carries_its_own_timestamp_and_author",
        ),
        # Confirmed is the only ending that ever touches the ledger; rejected
        # and pending both leave savings_entry_id null.
        CheckConstraint(
            "(state = 'confirmed') = (savings_entry_id IS NOT NULL)",
            name="only_a_confirmation_names_its_ledger_entry",
        ),
    )

    def __repr__(self) -> str:
        return f"<PendingSavingsDeposit {self.state.value} {self.amount_pence}p>"
