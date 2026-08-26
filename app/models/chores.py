"""Chore definitions, and the instances derived from them.

A definition is a rule and may be edited at any time. An instance is a fact
about one day or one week: it was claimed, or confirmed, or missed. Instances
belong to open weeks and are working data, so they may point at definitions
freely. What must never point at a definition is a settled figure — see
app/models/weeks.py, where a closed week keeps its own copy of everything it
paid for.
"""

from __future__ import annotations

from collections.abc import Iterable
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
from app.models.enums import Cadence, Category, InstanceState, MissOrigin

#: Lowercase, index-compatible with date.weekday() (0=Monday..6=Sunday) and
#: with week_view.WEEKDAY_NAMES — the display form starts "Monday" at the
#: same index. This is the stored and typed form for a WEEKDAYS chore.
WEEKDAY_TOKENS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def parse_weekday_tokens(tokens: Iterable[str]) -> frozenset[int]:
    """Validate a set of day names, resolving each to its date.weekday() int.

    Raises ValueError naming the bad token, rather than silently dropping it
    — a chore due "tuesday,friday" that quietly becomes "friday" because of a
    typo is a chore that stops asking for Tuesday and nobody decided that.
    """
    indices: set[int] = set()
    for raw in tokens:
        token = raw.strip().lower()
        if token not in WEEKDAY_TOKENS:
            raise ValueError(
                f"{raw!r} is not a day of the week — use one of {', '.join(WEEKDAY_TOKENS)}."
            )
        indices.add(WEEKDAY_TOKENS.index(token))
    if not indices:
        raise ValueError("weekdays must name at least one day.")
    return frozenset(indices)


def format_weekdays(indices: Iterable[int]) -> str:
    """The canonical stored form: Monday-first, each day once."""
    return ",".join(WEEKDAY_TOKENS[i] for i in sorted(set(indices)))


def parse_weekdays(value: str) -> frozenset[int]:
    """Parse the stored, comma-joined form back to date.weekday() ints."""
    return parse_weekday_tokens(value.split(","))


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

    #: Which days it's due, for WEEKDAYS only. Null for every other cadence,
    #: and required for that one. Stored as WEEKDAY_TOKENS joined by commas,
    #: canonically Monday-first — see parse_weekdays/format_weekdays above.
    weekdays: Mapped[str | None] = mapped_column(String(64))

    #: Availability. A chore withdrawn from the scheme is switched off rather
    #: than deleted, because settled weeks and past instances still refer to
    #: it and the record of what was done has to survive.
    is_available: Mapped[bool] = mapped_column(nullable=False, default=True)

    #: Whether a parent marks this one directly rather than the child claiming
    #: it — the clock test, not the bed. Orthogonal to cadence: an administered
    #: chore still has a cadence and a normal frequency (see the make-good pool
    #: in the rules doc, where it sits beside chores the child claims), the
    #: difference is only who initiates the "done". Nothing in this schema
    #: enforces that yet — this column records the fact; the claim endpoint
    #: does not read it.
    is_administered: Mapped[bool] = mapped_column(nullable=False, default=False)

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
        CheckConstraint(
            "(cadence = 'weekdays' AND weekdays IS NOT NULL)"
            " OR (cadence <> 'weekdays' AND weekdays IS NULL)",
            name="weekdays_only_for_weekdays_cadence",
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

    #: Which slot this is, for a chore due n times in a week: 1 of 3, 2 of 3.
    #: One for every other cadence. It exists so the n slots of a weekly-count
    #: chore are separately claimable and separately unique, rather than one
    #: row with a quantity nobody can point at.
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    claimed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    missed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    #: How this miss came about, where it is one. A parent marking a chore
    #: missed is a decision and names its author; a miss established at
    #: settlement is the absence of anything having happened, and has no
    #: author to name. Recording which of the two it was keeps them from
    #: being read back as the same fact.
    miss_origin: Mapped[MissOrigin | None] = mapped_column(enum_column(MissOrigin))

    #: When a claim on this instance was last rejected, and how many times it
    #: has been. The state goes back to UNTOUCHED and stays provisional, so no
    #: rule depends on either of these — but without them a rejected claim is
    #: indistinguishable from a tap that never registered, and the child
    #: re-claims into the same refusal with no idea why. Three rejections would
    #: otherwise leave a row reading exactly like one nobody ever touched,
    #: which is a hole in a ledger whose whole purpose is saying what happened.
    #: A later claim does not clear either: it is history, not current state.
    rejected_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    rejection_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    #: Who authorised the state this instance is in. There is one parent
    #: today, so this is always the same string, and recording it anyway is
    #: the point: when a second parent is authorised alongside the first, the
    #: history already says which of them agreed what. A miss written by
    #: settlement rather than by a person records that instead.
    authorised_by: Mapped[str | None] = mapped_column(String(60))

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
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("rejection_count >= 0", name="rejection_count_not_negative"),
        CheckConstraint(
            "(state = 'missed') = (miss_origin IS NOT NULL)",
            name="a_miss_says_how_it_arose",
        ),
        # Nobody authorises an absence. A miss nothing happened to was
        # established by settlement, and inventing a person for it would make
        # the record say something untrue.
        CheckConstraint(
            "miss_origin <> 'inferred_at_settlement' OR authorised_by IS NULL",
            name="an_inferred_miss_has_no_author",
        ),
        # There is deliberately no "a parent-marked miss names the parent"
        # check any more, and its absence is the rule rather than an omission.
        # Marking a chore missed carries no PIN (see app/routers/claims.py),
        # so there is no credential behind it to name, and writing a parent's
        # name against something no parent authorised would be the same
        # untruth the check above exists to prevent. PARENT_MARKED still means
        # what it meant — decided while the week was open, as against inferred
        # from silence once it closed. Dropped by migration c3f8b21a7d40.
        CheckConstraint(
            "(rejection_count = 0 AND rejected_at IS NULL)"
            " OR (rejection_count > 0 AND rejected_at IS NOT NULL)",
            name="a_rejection_records_when_it_happened",
        ),
        # A confirmation is money, so it names who agreed it.
        CheckConstraint(
            "state <> 'confirmed' OR authorised_by IS NOT NULL",
            name="a_confirmation_names_its_author",
        ),
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
        # ...and a week-scoped one, at most one per slot. A weekly-count chore
        # legitimately has several in a week, numbered 1..n; a weekly condition
        # has exactly one, which is slot 1.
        Index(
            "uq_chore_instances_definition_week_sequence",
            "definition_id",
            "week_id",
            "sequence",
            unique=True,
            sqlite_where=due_date.is_(None),
        ),
    )

    def __repr__(self) -> str:
        when = self.due_date.isoformat() if self.due_date else f"week {self.week_id}"
        return f"<ChoreInstance {self.definition_id} {when} {self.state.value}>"
