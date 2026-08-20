"""Weeks, and the figures a closed week keeps for itself.

This module is where the scheme's central rule lives, so it is worth stating
plainly. A settled week is a closed event. Its amounts are stored, never
recomputed, and nothing about it is derived from a chore definition — because
a definition is a rule that will be edited, and editing a rule must not reach
backwards and change what a child was already paid.

The separation is modelled as two tables:

    Week            the closing figures: what the week paid, in total and by
                    category, written once when it closes.

    SettlementLine  one row per thing the week paid for, holding a copy of
                    the chore's name, category and amount as they stood at
                    the moment of settlement.

A SettlementLine carries `source_definition_id` for provenance, so a parent
can ask "which chore was that?". It is deliberately nullable, deliberately
ON DELETE SET NULL, and it is never read to work out money. The money is in
the line's own columns. If every definition in the database were deleted
tonight, every settled week would still know exactly what it paid and why.

The first migration also puts SQLite triggers behind all of this: a settled
week's figures cannot be updated, and a settlement line cannot be updated or
deleted at all. The rule is not left to the application to remember.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, enum_column, utcnow
from app.models.enums import Cadence, Category, WeekStatus


class Week(Base):
    """One Sunday-to-Saturday chore week.

    More than one may be open at a time, and each settles independently on its
    own figures. `start_date` is the Sunday, in Europe/London.
    """

    __tablename__ = "weeks"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[WeekStatus] = mapped_column(
        enum_column(WeekStatus), nullable=False, default=WeekStatus.OPEN
    )

    # --- The closing figures. Null while the week is open, written once when
    # it closes, and immutable from that moment. A voided week closes at zero:
    # it pays nothing, but its instances stay, so the record of what was
    # actually done survives.

    #: The base allowance for the week. Paid regardless of the chores, and
    #: zeroed only by a void.
    settled_base_pence: Mapped[int | None] = mapped_column(Integer)

    #: What the chore pay came to: all of what was at stake, or nothing.
    settled_chore_pay_pence: Mapped[int | None] = mapped_column(Integer)
    settled_bonus_pence: Mapped[int | None] = mapped_column(Integer)
    settled_reward_pence: Mapped[int | None] = mapped_column(Integer)
    settled_total_pence: Mapped[int | None] = mapped_column(Integer)

    #: When the week was closed, whether by settling or by voiding.
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    #: Why it was voided, if it was. A void is an unusual act and wants a note.
    void_reason: Mapped[str | None] = mapped_column(Text)

    # --- Overrides. Settlement proposes; a parent may settle on a different
    # assignment of make-goods, including one that pays less than the app
    # worked out. Recorded so that a week paying less than it might have does
    # not read, a year later, as though the app got its sums wrong.

    #: Who chose a different assignment. Null when the figures are the ones
    #: the app proposed, which is the ordinary case.
    overridden_by: Mapped[str | None] = mapped_column(String(60))

    #: Their reason, in their words.
    override_reason: Mapped[str | None] = mapped_column(Text)

    #: What the app would have paid, had nobody overridden it. Stored beside
    #: what was actually paid, because the difference between the two is the
    #: whole story and neither number means much alone.
    optimum_total_pence: Mapped[int | None] = mapped_column(Integer)

    # --- Payday. Recorded after settlement, which is why these stay writable.

    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    #: How much of this payday the child chose to put into savings. Recorded
    #: from first use, before any savings feature exists to read it.
    deposited_pence: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    instances: Mapped[list["ChoreInstance"]] = relationship(  # noqa: F821
        back_populates="week"
    )
    settlement_lines: Mapped[list[SettlementLine]] = relationship(
        back_populates="week", order_by="SettlementLine.id"
    )

    __table_args__ = (
        # The week runs Sunday to Saturday. SQLite stores a Date as an ISO
        # string, so strftime can hold us to it: %w is 0 on a Sunday.
        CheckConstraint(
            "CAST(strftime('%w', start_date) AS INTEGER) = 0",
            name="starts_on_a_sunday",
        ),
        CheckConstraint(
            "julianday(end_date) - julianday(start_date) = 6",
            name="runs_seven_days",
        ),
        CheckConstraint(
            "(status = 'open'"
            "   AND settled_total_pence IS NULL AND closed_at IS NULL)"
            " OR (status IN ('settled', 'voided')"
            "   AND settled_base_pence IS NOT NULL"
            "   AND settled_chore_pay_pence IS NOT NULL"
            "   AND settled_bonus_pence IS NOT NULL"
            "   AND settled_reward_pence IS NOT NULL"
            "   AND settled_total_pence IS NOT NULL"
            "   AND closed_at IS NOT NULL)",
            name="closed_weeks_carry_their_figures",
        ),
        # A voided week loses the base, the chore pay and the bonuses — the
        # three things a void actually takes away. Rewards were earned by
        # something happening rather than by the week going well, so they
        # settle through the ordinary path and survive it.
        CheckConstraint(
            "status <> 'voided' OR (settled_base_pence = 0"
            " AND settled_chore_pay_pence = 0 AND settled_bonus_pence = 0)",
            name="a_voided_week_loses_base_chore_pay_and_bonuses",
        ),
        CheckConstraint(
            "settled_base_pence IS NULL OR settled_base_pence >= 0",
            name="base_not_negative",
        ),
        CheckConstraint(
            "settled_chore_pay_pence IS NULL OR settled_chore_pay_pence >= 0",
            name="chore_pay_not_negative",
        ),
        CheckConstraint(
            "settled_bonus_pence IS NULL OR settled_bonus_pence >= 0",
            name="bonus_not_negative",
        ),
        CheckConstraint(
            "settled_reward_pence IS NULL OR settled_reward_pence >= 0",
            name="reward_not_negative",
        ),
        CheckConstraint(
            "settled_total_pence IS NULL OR settled_total_pence >= 0",
            name="total_not_negative",
        ),
        CheckConstraint(
            "settled_total_pence IS NULL OR settled_total_pence ="
            " settled_base_pence + settled_chore_pay_pence"
            " + settled_bonus_pence + settled_reward_pence",
            name="total_is_the_sum_of_its_parts",
        ),
        # An override belongs to a settled week, names who made it, and says
        # what it was chosen over.
        CheckConstraint(
            "overridden_by IS NULL OR (status = 'settled'"
            " AND optimum_total_pence IS NOT NULL)",
            name="an_override_is_recorded_in_full",
        ),
        CheckConstraint(
            "override_reason IS NULL OR overridden_by IS NOT NULL",
            name="only_an_override_has_a_reason",
        ),
        # An override that pays less than the app offered has to say why. The
        # turned-down figure is stored so the difference tells a story; without
        # a reason it tells the half a person could have worked out anyway.
        CheckConstraint(
            "overridden_by IS NULL"
            " OR settled_total_pence >= optimum_total_pence"
            " OR (override_reason IS NOT NULL AND length(trim(override_reason)) > 0)",
            name="an_override_that_costs_money_says_why",
        ),
        CheckConstraint(
            "optimum_total_pence IS NULL OR optimum_total_pence >= 0",
            name="optimum_not_negative",
        ),
        # You cannot pay a week that has not closed.
        CheckConstraint(
            "paid_at IS NULL OR status IN ('settled', 'voided')",
            name="only_a_closed_week_is_paid",
        ),
        # A deposit is never negative. It is deliberately not capped at this
        # week's settled total: a week can owe more than it settled for, since
        # a parent-entered reward belongs to the week without being part of
        # the chore result. What a deposit may not exceed is what was actually
        # handed over, and only the payment knows that.
        CheckConstraint(
            "deposited_pence IS NULL OR deposited_pence >= 0",
            name="deposit_not_negative",
        ),
    )

    @property
    def is_closed(self) -> bool:
        return self.status in (WeekStatus.SETTLED, WeekStatus.VOIDED)

    def __repr__(self) -> str:
        return f"<Week {self.start_date.isoformat()} {self.status.value}>"


class SettlementLine(Base):
    """One line of a closed week's figures, holding its own copy of the facts.

    Every column needed to explain the payment is here: the chore's name as it
    read that week, its category and cadence, the amount it paid then, and how
    many of them there were. Nothing here is a lookup.

    Append-only, enforced by trigger. A mistake in a settled week is corrected
    by recording something new, never by editing the record of what happened.
    """

    __tablename__ = "settlement_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(
        ForeignKey("weeks.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # --- The copy. These are the money, and they are never looked up again.

    chore_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[Category] = mapped_column(enum_column(Category), nullable=False)
    cadence: Mapped[Cadence] = mapped_column(enum_column(Cadence), nullable=False)

    #: What one of these paid, at the moment the week closed.
    unit_amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: What this line actually contributed. Zero is legitimate: a chore
    #: worked to recover a miss is recorded, and pays nothing.
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Provenance only. Nullable, and set to null if the definition is ever
    #: deleted, precisely so that deleting one cannot take a settled figure
    #: with it. Never read to compute an amount.
    source_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("chore_definitions.id", ondelete="SET NULL")
    )

    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    week: Mapped[Week] = relationship(back_populates="settlement_lines")

    __table_args__ = (
        CheckConstraint("unit_amount_pence >= 0", name="unit_amount_not_negative"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("amount_pence >= 0", name="amount_not_negative"),
    )

    def __repr__(self) -> str:
        return f"<SettlementLine {self.chore_name!r} {self.amount_pence}p>"
