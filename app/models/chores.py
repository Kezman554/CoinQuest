"""Chore definitions, and the instances derived from them.

A definition is a rule and may be edited at any time. An instance is a fact
about one day or one week: it was claimed, or confirmed, or missed. Instances
belong to open weeks and are working data, so they may point at definitions
freely. What must never point at a definition is a settled figure — see
app/models/weeks.py, where a closed week keeps its own copy of everything it
paid for.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UtcDateTime, enum_column, utcnow
from app.models.enums import Cadence, Category, InstanceState


class ChoreDefinition(Base):
    """A chore as written down in the scheme.

    Editable, and expected to be edited: the amounts and the list of chores
    are reviewed on a schedule. Editing one changes what happens from now on
    and never what a settled week already paid.
    """

    __tablename__ = "chore_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    cadence: Mapped[Cadence] = mapped_column(enum_column(Cadence), nullable=False)
    category: Mapped[Category] = mapped_column(enum_column(Category), nullable=False)

    #: What it pays, in pence. For a basic chore this is its share of the
    #: weekly chore pay; for a bonus, the all-or-nothing weekly amount.
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: How many times a week, for WEEKLY_COUNT only. Null for every other
    #: cadence, and required for that one.
    times_per_week: Mapped[int | None] = mapped_column(Integer)

    #: Availability. A chore withdrawn from the scheme is switched off rather
    #: than deleted, because settled weeks and past instances still refer to
    #: it and the record of what was done has to survive.
    is_available: Mapped[bool] = mapped_column(nullable=False, default=True)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    instances: Mapped[list[ChoreInstance]] = relationship(back_populates="definition")

    __table_args__ = (
        # There are no fines and no deductions of any kind, so no amount in
        # the scheme is ever negative.
        CheckConstraint("amount_pence >= 0", name="amount_not_negative"),
        CheckConstraint(
            "(cadence = 'weekly_count' AND times_per_week IS NOT NULL"
            " AND times_per_week > 0)"
            " OR (cadence <> 'weekly_count' AND times_per_week IS NULL)",
            name="times_per_week_only_for_weekly_count",
        ),
    )

    def __repr__(self) -> str:
        return f"<ChoreDefinition {self.name!r} {self.category.value}>"


class ChoreInstance(Base):
    """One occasion on which a chore was, or was not, done.

    Daily and one-off chores get an instance per day. Week-scoped cadences get
    one instance for the week, judged once. An instance starts UNTOUCHED and
    only becomes a miss when a parent says so or the week settles.
    """

    __tablename__ = "chore_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("chore_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    week_id: Mapped[int] = mapped_column(
        ForeignKey("weeks.id", ondelete="RESTRICT"), nullable=False
    )

    #: The local London day this instance belongs to. Null for a week-scoped
    #: cadence, which belongs to the week as a whole.
    due_date: Mapped[date | None] = mapped_column(Date)

    state: Mapped[InstanceState] = mapped_column(
        enum_column(InstanceState), nullable=False, default=InstanceState.UNTOUCHED
    )

    #: How many of the week's required count this instance accounts for. One
    #: for everything except a WEEKLY_COUNT chore, where the parent may
    #: confirm several at once.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    claimed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    missed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    #: Set when this instance was spent recovering a miss, at settlement. A
    #: recovery is worked unpaid, so it is confirmed but pays nothing.
    recovered_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("chore_instances.id", ondelete="SET NULL")
    )

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow
    )

    definition: Mapped[ChoreDefinition] = relationship(back_populates="instances")
    week: Mapped["Week"] = relationship(back_populates="instances")  # noqa: F821

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "(state = 'claimed' AND claimed_at IS NOT NULL)"
            " OR (state = 'confirmed' AND confirmed_at IS NOT NULL)"
            " OR (state = 'missed' AND missed_at IS NOT NULL)"
            " OR state = 'untouched'",
            name="state_carries_its_timestamp",
        ),
        CheckConstraint(
            "recovered_instance_id IS NULL OR recovered_instance_id <> id",
            name="an_instance_cannot_recover_itself",
        ),
        # A day-scoped chore gets at most one instance per day...
        Index(
            "uq_chore_instances_definition_day",
            "definition_id",
            "due_date",
            unique=True,
            sqlite_where=due_date.isnot(None),
        ),
        # ...and a week-scoped one, at most one per week.
        Index(
            "uq_chore_instances_definition_week",
            "definition_id",
            "week_id",
            unique=True,
            sqlite_where=due_date.is_(None),
        ),
    )

    def __repr__(self) -> str:
        when = self.due_date.isoformat() if self.due_date else f"week {self.week_id}"
        return f"<ChoreInstance {self.definition_id} {when} {self.state.value}>"
