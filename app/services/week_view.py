"""The week as the child reads it, standing at the kitchen screen.

Everything here is presentation of facts the scheme services already worked
out. Nothing in this module decides money: the figures come from
`settlement.propose`, the requirement comes from `instances.plan_week`, and
what happened comes from the stored instances. It writes nothing.

Two groupings, because they are two different things and reading them the same
way is how a child ends up thinking he is behind when he is not:

  - A **daily** chore belongs to a day. Monday's washing-up is a fact about
    Monday, and an empty Tuesday is a question about Tuesday.
  - A **weekly-count** chore belongs to the week. "Three times before Saturday"
    has no day attached, and showing it seven times, greyed out on four of
    them, invents an absence the scheme never asked about.
  - A **week-long condition** belongs to the week too, and cannot be claimed at
    all. It is judged once, at settlement, so it is shown as a standing
    condition rather than as anything with a button on it.

An untouched instance on a day already past is still claimable, and that is
deliberate. It is provisional until the week settles, so "you did not tick
Monday" must not read as "Monday is lost".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chores import ChoreDefinition, ChoreInstance
from app.models.enums import (
    ON_DEMAND_CADENCES,
    Cadence,
    Category,
    InstanceState,
    WeekStatus,
)
from app.models.waivers import Waiver
from app.models.weeks import Week
from app.services import settlement
from app.services.calendar import Period, elapsed, today
from app.services.instances import WeekPlan, plan_week

#: How much of the recovery window has to be left before the wording changes.
#: A day is the honest threshold: below it there is no tomorrow to do the
#: chore in, so "you have until Saturday" stops being useful advice.
URGENT_WITHIN_SECONDS = 24 * 60 * 60

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@dataclass(frozen=True)
class InstanceCard:
    """One thing on the screen with, at most, one button on it."""

    instance_id: int | None
    definition_id: int
    name: str
    category: Category
    cadence: Cadence
    amount_pence: int
    state: str
    sequence: int
    due_date: date | None
    can_claim: bool
    rejection_count: int
    miss_origin: str | None


@dataclass(frozen=True)
class DayCard:
    """One day of the week, and the daily chores that fall on it."""

    day: date
    weekday: str
    is_today: bool
    is_past: bool
    waived: bool
    waiver_reason: str | None
    chores: tuple[InstanceCard, ...]


@dataclass(frozen=True)
class WeeklyCard:
    """A chore the week asks for, with no day attached to it."""

    definition_id: int
    name: str
    category: Category
    cadence: Cadence
    amount_pence: int
    required: int
    confirmed: int
    claimed: int
    instances: tuple[InstanceCard, ...]
    judged_at_settlement: bool
    waived: bool


@dataclass(frozen=True)
class RecoveryNeed:
    """One miss that has actually been ruled, and what covers it if anything."""

    definition_id: int
    miss_name: str
    covered_by: str | None


@dataclass(frozen=True)
class RecoveryView:
    """What is outstanding, what could cover it, and how long is left.

    `deadline` is the last day of the week, because the recovery window closes
    when the week does. `seconds_remaining` counts to the first instant of the
    next week — the half-open end — and goes through `elapsed`, so a week
    containing a clock change measures the hours it actually has.
    """

    needs: tuple[RecoveryNeed, ...]
    outstanding: int
    covered: int
    cap: int
    deadline: date
    seconds_remaining: int
    days_remaining: int
    urgent: bool
    options: tuple[InstanceCard, ...]
    spent: tuple[InstanceCard, ...]


@dataclass(frozen=True)
class Totals:
    base_pence: int
    chore_pay_at_stake_pence: int
    chore_pay_pence: int
    chore_pay_awarded: bool
    bonus_pence: int
    reward_pence: int
    total_pence: int


@dataclass(frozen=True)
class WeekView:
    child_name: str
    week_id: int
    start_date: date
    end_date: date
    status: WeekStatus
    today: date
    days: tuple[DayCard, ...]
    weekly: tuple[WeeklyCard, ...]
    waived_days: tuple[date, ...]
    recovery: RecoveryView
    totals: Totals


def build(
    session: Session, week: Week, tz: tzinfo, *, now: datetime | None = None
) -> WeekView:
    """Assemble the child's view of one open week. Writes nothing."""
    now = now or datetime.now(tz)
    period = settlement.week_period(week, tz)

    definitions = {
        definition.id: definition for definition in session.query(ChoreDefinition).all()
    }
    waivers = session.query(Waiver).all()
    instances = (
        session.query(ChoreInstance).filter(ChoreInstance.week_id == week.id).all()
    )
    plan = plan_week(period, definitions.values(), waivers, week_id=week.id)
    proposal = settlement.propose(session, week, tz)

    open_week = week.status is WeekStatus.OPEN
    day_reasons = {
        waiver.day: waiver.reason
        for waiver in waivers
        if waiver.day is not None and period.contains_day(waiver.day)
    }
    waived_definitions = {
        waiver.definition_id
        for waiver in waivers
        if waiver.week_id == week.id and waiver.definition_id is not None
    }

    cards = [_card(instance, definitions, open_week) for instance in instances]
    local_today = today(tz)

    return WeekView(
        child_name=get_settings().child_name,
        week_id=week.id,
        start_date=week.start_date,
        end_date=week.end_date,
        status=week.status,
        today=local_today,
        days=_days(period, cards, plan.waived_days, day_reasons, local_today),
        weekly=_weekly(plan, proposal, cards, definitions, waived_definitions),
        waived_days=plan.waived_days,
        recovery=_recovery(proposal, cards, period, now, open_week),
        totals=Totals(
            base_pence=proposal.base_pence,
            chore_pay_at_stake_pence=proposal.chore_pay_at_stake_pence,
            chore_pay_pence=proposal.chore_pay_pence,
            chore_pay_awarded=proposal.chore_pay_awarded,
            bonus_pence=proposal.bonus_pence,
            reward_pence=proposal.reward_pence,
            total_pence=proposal.total_pence,
        ),
    )


def _card(
    instance: ChoreInstance,
    definitions: dict[int, ChoreDefinition],
    open_week: bool,
) -> InstanceCard:
    definition = definitions[instance.definition_id]
    return InstanceCard(
        instance_id=instance.id,
        definition_id=instance.definition_id,
        name=definition.name,
        category=definition.category,
        cadence=definition.cadence,
        amount_pence=definition.amount_pence,
        state=instance.state.value,
        sequence=instance.sequence,
        due_date=instance.due_date,
        # A day already past is still claimable. Nothing becomes a miss until
        # a parent says so or the week settles.
        can_claim=open_week and instance.state is InstanceState.UNTOUCHED,
        rejection_count=instance.rejection_count,
        miss_origin=instance.miss_origin.value if instance.miss_origin else None,
    )


def _days(
    period: Period,
    cards: list[InstanceCard],
    waived_days: tuple[date, ...],
    day_reasons: dict[date, str | None],
    local_today: date,
) -> tuple[DayCard, ...]:
    """Every day of the week, in order, whether or not it asks for anything.

    A waived day keeps its place in the row. Leaving it out would make the
    week look six days long; showing it empty would make it look like a day
    nothing was done on. It was a day away, which is a third thing.
    """
    by_day: dict[date, list[InstanceCard]] = {}
    for card in cards:
        if card.due_date is not None:
            by_day.setdefault(card.due_date, []).append(card)

    return tuple(
        DayCard(
            day=day,
            weekday=WEEKDAY_NAMES[day.weekday()],
            is_today=day == local_today,
            is_past=day < local_today,
            waived=day in waived_days,
            waiver_reason=day_reasons.get(day),
            chores=tuple(sorted(by_day.get(day, []), key=lambda card: card.name)),
        )
        for day in period.days
    )


def _weekly(
    plan: WeekPlan,
    proposal: settlement.Proposal,
    cards: list[InstanceCard],
    definitions: dict[int, ChoreDefinition],
    waived_definitions: set[int],
) -> tuple[WeeklyCard, ...]:
    """The count-based chores and the week-long conditions, one card each."""
    by_definition: dict[int, list[InstanceCard]] = {}
    for card in cards:
        if card.due_date is None:
            by_definition.setdefault(card.definition_id, []).append(card)

    required = {
        requirement.definition_id: requirement.required
        for requirement in proposal.requirements
    }

    weekly: list[WeeklyCard] = []
    for definition_id, group in by_definition.items():
        definition = definitions[definition_id]
        weekly.append(
            WeeklyCard(
                definition_id=definition_id,
                name=definition.name,
                category=definition.category,
                cadence=definition.cadence,
                amount_pence=definition.amount_pence,
                required=required.get(definition_id, len(group)),
                confirmed=sum(1 for card in group if card.state == "confirmed"),
                claimed=sum(1 for card in group if card.state == "claimed"),
                instances=tuple(sorted(group, key=lambda card: card.sequence)),
                judged_at_settlement=False,
                waived=definition_id in waived_definitions,
            )
        )

    # A week-long condition produces no instance at all. It is a judgement
    # deferred to settlement, and it belongs on the screen as one: something
    # being kept up all week, with nothing to tap.
    for judgement in plan.deferred:
        definition = definitions[judgement.definition_id]
        weekly.append(
            WeeklyCard(
                definition_id=judgement.definition_id,
                name=judgement.definition_name,
                category=judgement.category,
                cadence=definition.cadence,
                amount_pence=definition.amount_pence,
                required=1,
                confirmed=0,
                claimed=0,
                instances=(),
                judged_at_settlement=True,
                waived=judgement.definition_id in waived_definitions,
            )
        )

    return tuple(sorted(weekly, key=lambda card: card.name))


def _recovery(
    proposal: settlement.Proposal,
    cards: list[InstanceCard],
    period: Period,
    now: datetime,
    open_week: bool,
) -> RecoveryView:
    """What has actually been ruled missed, and what could still cover it.

    Only a parent-marked miss appears here. The proposal also carries the
    misses settlement *would* infer from everything still untouched, and
    telling a child on Monday that he has missed Thursday's chore would be
    both untrue and the opposite of what the recovery window is for. A miss
    the child has to act on is one somebody has ruled.

    Coverage is worked out here rather than read off `proposal.recoveries`,
    and the difference matters mid-week. The proposal's assignment is about
    the week as it will end, so on Monday — with six days of chores still
    untouched and therefore counted as prospective misses — it exceeds the cap
    and correctly declines to recover anything. That is the right answer for
    the money and the wrong thing to put on the screen: what the child needs
    to know is whether the miss he has been told about is put right, not what
    the week would pay if it stopped now. Settlement decides the money, on the
    week that actually happened, and is not bound by anything said here.
    """
    definite = [miss for miss in proposal.misses if miss.is_definite]

    met = {
        requirement.definition_id
        for requirement in proposal.requirements
        if requirement.met
    }
    # Cheapest first, which is what the optimiser prefers too: spending a 300p
    # bonus where a 100p one would do is exactly the mistake it avoids.
    available = sorted(
        (
            requirement
            for requirement in proposal.requirements
            if requirement.can_be_spent_as_recovery
        ),
        key=lambda requirement: (requirement.amount_pence, requirement.name),
    )

    needs: list[RecoveryNeed] = []
    spent_names: list[str] = []
    for miss in definite:
        covered_by = None
        # The cap is on the whole week, not on any one chore.
        if available and len(spent_names) < proposal.cap:
            covered_by = available.pop(0).name
            spent_names.append(covered_by)
        needs.append(
            RecoveryNeed(
                definition_id=miss.definition_id,
                miss_name=miss.name,
                covered_by=covered_by,
            )
        )
    # What could still be worked to cover a miss: a bonus chore the child can
    # decide to do today, that the week has not already got. The instance is
    # the tappable thing, so the option is an instance rather than a chore.
    options = tuple(
        card
        for card in cards
        if card.category is Category.BONUS
        and card.cadence in ON_DEMAND_CADENCES
        and card.definition_id not in met
        and card.can_claim
    )
    # The bonus chores actually doing the covering. Worked, and given up: a
    # recovery is done unpaid, and the screen has to say so rather than let a
    # bonus look like it is being paid for twice.
    spent = tuple(
        card
        for card in cards
        if card.name in spent_names and card.state == InstanceState.CONFIRMED.value
    )

    seconds = int(elapsed(now, period.ends_before).total_seconds()) if open_week else 0
    seconds = max(seconds, 0)
    outstanding = sum(1 for need in needs if need.covered_by is None)

    return RecoveryView(
        needs=tuple(needs),
        outstanding=outstanding,
        covered=len(needs) - outstanding,
        cap=proposal.cap,
        deadline=period.end,
        seconds_remaining=seconds,
        days_remaining=seconds // (24 * 60 * 60),
        urgent=outstanding > 0 and seconds < URGENT_WITHIN_SECONDS,
        options=options,
        spent=spent,
    )
