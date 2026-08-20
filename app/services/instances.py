"""Working out which instances a week actually asks for.

A definition says what the scheme expects in general. This module turns that
into the concrete list for one particular week, after the waivers have had
their say. Nothing here writes anything or reads a clock: it takes a week, a
set of definitions and a set of waivers, and returns what should exist.

Three cadences are generated here:

    DAILY             one instance for each day the week contains
    WEEKLY_COUNT      n instances, tied to no day, numbered 1..n
    WEEKLY_CONDITION  nothing now; one judgement, made at settlement

The other two are not derived from a week at all. A ONE_OFF is created when a
parent adds it, on the day they choose, and an EVENT when a parent logs that
it happened. Neither can be predicted from a definition, so neither is
generated here.

Waivers subtract from all of that. A waived day removes that day's daily
instances. A chore waived for a week removes it entirely, whatever its
cadence. And a weekly count scales down by how many days were waived,
according to the bands below.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from app.models.enums import Cadence, Category, InstanceState, WaiverScope
from app.services.calendar import Period


@dataclass(frozen=True)
class CountBand:
    """One row of the table that scales a weekly count by days waived.

    `reduce_by` is how many occasions come off the required count.
    `waives_entirely` means the chore is not assessed at all that week, which
    is a different statement from a count that happens to reach zero.
    """

    up_to_days_waived: int
    reduce_by: int = 0
    waives_entirely: bool = False

    def apply(self, times_per_week: int) -> int:
        if self.waives_entirely:
            return 0
        return max(times_per_week - self.reduce_by, 0)


#: How a weekly count scales with days away. Bands, not branches: these are
#: reviewed along with the rest of the scheme and are expected to change, so
#: changing them should mean editing this table and nothing else.
#:
#:      0-2 days waived   the full count still stands
#:      3-4 days waived   one occasion comes off: 3x becomes 2x, 2x becomes 1x
#:      5-7 days waived   the chore is not assessed at all
#:
#: Bands are read in order and the first whose ceiling covers the days waived
#: is the one that applies, so they must stay sorted and must cover all seven.
WEEKLY_COUNT_BANDS: tuple[CountBand, ...] = (
    CountBand(up_to_days_waived=2, reduce_by=0),
    CountBand(up_to_days_waived=4, reduce_by=1),
    CountBand(up_to_days_waived=7, waives_entirely=True),
)


def band_for(days_waived: int, bands: Sequence[CountBand] = WEEKLY_COUNT_BANDS) -> CountBand:
    """The band covering this many waived days."""
    if days_waived < 0:
        raise ValueError("Days waived cannot be negative.")
    for band in bands:
        if days_waived <= band.up_to_days_waived:
            return band
    raise ValueError(
        f"No band covers {days_waived} waived days; the table must cover a whole week."
    )


def scaled_weekly_count(
    times_per_week: int,
    days_waived: int,
    bands: Sequence[CountBand] = WEEKLY_COUNT_BANDS,
) -> int:
    """How many times a chore is required, given the days waived."""
    return band_for(days_waived, bands).apply(times_per_week)


@dataclass(frozen=True)
class PlannedInstance:
    """One occasion the week asks for. Not yet a row."""

    definition_id: int
    definition_name: str
    cadence: Cadence
    category: Category
    due_date: date | None
    sequence: int = 1
    quantity: int = 1


@dataclass(frozen=True)
class DeferredJudgement:
    """A week-long condition, to be judged once, at settlement and not before.

    It appears in the plan so the week's view can show it as outstanding,
    which is not the same as generating an instance for it.
    """

    definition_id: int
    definition_name: str
    category: Category


@dataclass(frozen=True)
class Exclusion:
    """Something the scheme would have asked for, and a waiver removed."""

    definition_id: int
    definition_name: str
    reason: str
    due_date: date | None = None


@dataclass(frozen=True)
class WeekPlan:
    """Everything one week asks for, after the waivers."""

    week: Period
    instances: tuple[PlannedInstance, ...]
    deferred: tuple[DeferredJudgement, ...]
    waived_days: tuple[date, ...]
    exclusions: tuple[Exclusion, ...]

    @property
    def days_waived(self) -> int:
        return len(self.waived_days)

    def for_definition(self, definition_id: int) -> tuple[PlannedInstance, ...]:
        return tuple(
            instance
            for instance in self.instances
            if instance.definition_id == definition_id
        )

    def count_for(self, definition_id: int) -> int:
        """How many occasions this chore is asked for. Zero if it was waived."""
        return len(self.for_definition(definition_id))


def waived_days_in(week: Period, waivers: Iterable) -> tuple[date, ...]:
    """The days of this week that a day-waiver covers, in order."""
    days = {
        waiver.day
        for waiver in waivers
        if waiver.scope is WaiverScope.DAY
        and waiver.day is not None
        and week.contains_day(waiver.day)
    }
    return tuple(sorted(days))


def waived_definition_ids(week_id: int | None, waivers: Iterable) -> frozenset[int]:
    """Chores excused for this week entirely."""
    return frozenset(
        waiver.definition_id
        for waiver in waivers
        if waiver.scope is WaiverScope.CHORE_WEEK
        and waiver.definition_id is not None
        and (week_id is None or waiver.week_id == week_id)
    )


def plan_week(
    week: Period,
    definitions: Iterable,
    waivers: Iterable = (),
    *,
    week_id: int | None = None,
    bands: Sequence[CountBand] = WEEKLY_COUNT_BANDS,
) -> WeekPlan:
    """What this week asks for, given these definitions and these waivers.

    Pure: it reads no clock and writes nothing. `week` is a Period from
    app.services.calendar, so the days it contains were already resolved in
    Europe/London by whoever built it.
    """
    waived_days = waived_days_in(week, waivers)
    excused = waived_definition_ids(week_id, waivers)

    instances: list[PlannedInstance] = []
    deferred: list[DeferredJudgement] = []
    exclusions: list[Exclusion] = []

    for definition in sorted(definitions, key=lambda d: (d.name, d.id)):
        if not definition.is_available:
            continue

        if definition.id in excused:
            exclusions.append(
                Exclusion(
                    definition_id=definition.id,
                    definition_name=definition.name,
                    reason="the chore was waived for this week",
                )
            )
            continue

        if definition.cadence is Cadence.DAILY:
            for day in week.days:
                if day in waived_days:
                    exclusions.append(
                        Exclusion(
                            definition_id=definition.id,
                            definition_name=definition.name,
                            reason="the day was waived",
                            due_date=day,
                        )
                    )
                    continue
                instances.append(
                    PlannedInstance(
                        definition_id=definition.id,
                        definition_name=definition.name,
                        cadence=definition.cadence,
                        category=definition.category,
                        due_date=day,
                    )
                )

        elif definition.cadence is Cadence.WEEKLY_COUNT:
            required = scaled_weekly_count(
                definition.times_per_week, len(waived_days), bands
            )
            if required == 0:
                exclusions.append(
                    Exclusion(
                        definition_id=definition.id,
                        definition_name=definition.name,
                        reason=(
                            f"{len(waived_days)} days waived scales"
                            f" {definition.times_per_week}x to nothing"
                        ),
                    )
                )
                continue
            for slot in range(1, required + 1):
                instances.append(
                    PlannedInstance(
                        definition_id=definition.id,
                        definition_name=definition.name,
                        cadence=definition.cadence,
                        category=definition.category,
                        due_date=None,   # tied to the week, not to a day
                        sequence=slot,
                    )
                )

        elif definition.cadence is Cadence.WEEKLY_CONDITION:
            # Judged once, at settlement. Deliberately not an instance now:
            # a condition held all week cannot be assessed before the week
            # has finished happening.
            deferred.append(
                DeferredJudgement(
                    definition_id=definition.id,
                    definition_name=definition.name,
                    category=definition.category,
                )
            )

        # ONE_OFF and EVENT are created by a parent, not derived from a week.

    return WeekPlan(
        week=week,
        instances=tuple(instances),
        deferred=tuple(deferred),
        waived_days=waived_days,
        exclusions=tuple(exclusions),
    )


def sync_week_instances(session, week, plan: WeekPlan) -> tuple[int, int]:
    """Bring the stored instances for a week into line with its plan.

    Returns (created, removed).

    Two rules govern this, and both are about not destroying work:

    - An instance the plan still asks for is left exactly as it is. Claims and
      confirmations are facts, and regenerating a week must never reset one.
    - An instance the plan no longer asks for is removed only if it is still
      UNTOUCHED. If a day is waived after the child already claimed something
      on it, the claim stays and a parent decides what to do with it. Silently
      deleting somebody's confirmed work is not a thing this app does.
    """
    from app.models.chores import ChoreInstance

    existing = {
        (instance.definition_id, instance.due_date, instance.sequence): instance
        for instance in session.query(ChoreInstance).filter(
            ChoreInstance.week_id == week.id
        )
    }
    wanted = {
        (planned.definition_id, planned.due_date, planned.sequence): planned
        for planned in plan.instances
    }

    created = 0
    for key, planned in wanted.items():
        if key in existing:
            continue
        session.add(
            ChoreInstance(
                definition_id=planned.definition_id,
                week_id=week.id,
                due_date=planned.due_date,
                sequence=planned.sequence,
                quantity=planned.quantity,
                state=InstanceState.UNTOUCHED,
            )
        )
        created += 1

    removed = 0
    for key, instance in existing.items():
        if key in wanted:
            continue
        if instance.state is not InstanceState.UNTOUCHED:
            continue  # somebody did something here; it is not ours to erase
        session.delete(instance)
        removed += 1

    session.flush()
    return created, removed
