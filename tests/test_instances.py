"""Generating a week's assessable instances.

The planning tests are pure: they build definitions and waivers in memory and
never touch the database, because none of this depends on storage. The last
group persists a plan, to check that regenerating a week cannot destroy work
somebody has already done.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import Cadence, Category, InstanceState, WaiverScope
from app.services.calendar import week_containing
from app.services.instances import (
    WEEKLY_COUNT_BANDS,
    CountBand,
    band_for,
    plan_week,
    scaled_weekly_count,
    sync_week_instances,
)

LONDON = ZoneInfo("Europe/London")
WEEK = week_containing(date(2026, 8, 16), LONDON)  # Sun 16th to Sat 22nd
SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY = WEEK.days
NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


# --- Stand-ins for the rows, so the planner can be tested without a database


@dataclass
class FakeDefinition:
    id: int
    name: str
    cadence: Cadence
    category: Category = Category.BASIC
    amount_pence: int = 50
    times_per_week: int | None = None
    is_available: bool = True


@dataclass
class FakeWaiver:
    scope: WaiverScope
    day: date | None = None
    week_id: int | None = None
    definition_id: int | None = None


def day_waivers(*days: date, week_id: int = 1) -> list[FakeWaiver]:
    return [FakeWaiver(scope=WaiverScope.DAY, day=day) for day in days]


DAILY = FakeDefinition(id=1, name="Make bed", cadence=Cadence.DAILY)
TWICE = FakeDefinition(
    id=2, name="Bins", cadence=Cadence.WEEKLY_COUNT, times_per_week=2
)
THRICE = FakeDefinition(
    id=3, name="Hoover", cadence=Cadence.WEEKLY_COUNT, times_per_week=3
)
CONDITION = FakeDefinition(
    id=4, name="Room tidy all week", cadence=Cadence.WEEKLY_CONDITION
)
ONE_OFF = FakeDefinition(id=5, name="Clear the shed", cadence=Cadence.ONE_OFF)
EVENT = FakeDefinition(
    id=6, name="School award", cadence=Cadence.EVENT, category=Category.REWARD
)


# --- 1. Daily ---------------------------------------------------------------


def test_a_daily_chore_produces_one_instance_per_day():
    plan = plan_week(WEEK, [DAILY])
    assert plan.count_for(DAILY.id) == 7
    assert [instance.due_date for instance in plan.instances] == list(WEEK.days)


def test_a_daily_chore_produces_seven_even_in_the_week_the_clocks_change():
    # The October week is 169 hours long. It is still seven days.
    october = week_containing(date(2026, 10, 25), LONDON)
    assert plan_week(october, [DAILY]).count_for(DAILY.id) == 7


# --- 2. Weekly count --------------------------------------------------------


def test_a_weekly_count_chore_produces_n_instances_tied_to_no_day():
    plan = plan_week(WEEK, [THRICE])
    planned = plan.for_definition(THRICE.id)
    assert len(planned) == 3
    assert all(instance.due_date is None for instance in planned)
    # Numbered, so each of the three is separately claimable.
    assert [instance.sequence for instance in planned] == [1, 2, 3]


# --- 3. Weekly condition ----------------------------------------------------


def test_a_weekly_condition_produces_no_instance_before_settlement():
    plan = plan_week(WEEK, [CONDITION])
    assert plan.instances == ()
    # It is still visible as outstanding, which is not the same as existing.
    assert [judgement.definition_id for judgement in plan.deferred] == [CONDITION.id]


def test_one_off_and_event_chores_are_not_derived_from_a_week():
    # Both are created by a parent when they happen; neither is predictable
    # from a definition, so the planner leaves them alone entirely.
    plan = plan_week(WEEK, [ONE_OFF, EVENT])
    assert plan.instances == ()
    assert plan.deferred == ()


def test_an_unavailable_chore_produces_nothing():
    withdrawn = FakeDefinition(
        id=9, name="Old chore", cadence=Cadence.DAILY, is_available=False
    )
    assert plan_week(WEEK, [withdrawn]).instances == ()


# --- 4. Waivers -------------------------------------------------------------


def test_a_waived_day_removes_that_days_daily_instances():
    plan = plan_week(WEEK, [DAILY], day_waivers(WEDNESDAY))
    assert plan.count_for(DAILY.id) == 6
    assert WEDNESDAY not in [instance.due_date for instance in plan.instances]
    assert plan.waived_days == (WEDNESDAY,)


def test_a_waived_day_says_what_it_removed_and_why():
    plan = plan_week(WEEK, [DAILY], day_waivers(WEDNESDAY))
    (exclusion,) = plan.exclusions
    assert exclusion.due_date == WEDNESDAY
    assert exclusion.reason == "the day was waived"


def test_a_chore_waived_for_the_week_is_removed_entirely():
    waivers = [
        FakeWaiver(scope=WaiverScope.CHORE_WEEK, week_id=1, definition_id=DAILY.id)
    ]
    plan = plan_week(WEEK, [DAILY, THRICE], waivers, week_id=1)
    assert plan.count_for(DAILY.id) == 0
    assert plan.count_for(THRICE.id) == 3  # the other chore is untouched
    assert plan.exclusions[0].reason == "the chore was waived for this week"


def test_a_chore_waiver_for_another_week_does_not_apply():
    waivers = [
        FakeWaiver(scope=WaiverScope.CHORE_WEEK, week_id=99, definition_id=DAILY.id)
    ]
    assert plan_week(WEEK, [DAILY], waivers, week_id=1).count_for(DAILY.id) == 7


def test_a_waiver_for_a_day_outside_the_week_is_ignored():
    plan = plan_week(WEEK, [DAILY], day_waivers(date(2026, 9, 2)))
    assert plan.count_for(DAILY.id) == 7
    assert plan.waived_days == ()


def test_a_weekly_condition_survives_a_waived_day():
    # A week-long condition is not made of days, so waiving one does not
    # reduce it. Only a chore-week waiver removes it.
    plan = plan_week(WEEK, [CONDITION], day_waivers(MONDAY, TUESDAY, WEDNESDAY))
    assert len(plan.deferred) == 1


# --- 5. The bands, which are data ------------------------------------------


@pytest.mark.parametrize(
    ("days_waived", "twice", "thrice"),
    [
        (0, 2, 3),
        (1, 2, 3),
        (2, 2, 3),  # 0-2: the full count stands
        (3, 1, 2),
        (4, 1, 2),  # 3-4: one occasion comes off
        (5, 0, 0),
        (6, 0, 0),
        (7, 0, 0),  # 5-7: not assessed at all
    ],
)
def test_the_scaling_table(days_waived, twice, thrice):
    assert scaled_weekly_count(2, days_waived) == twice
    assert scaled_weekly_count(3, days_waived) == thrice


def test_the_bands_cover_a_whole_week_and_stay_sorted():
    ceilings = [band.up_to_days_waived for band in WEEKLY_COUNT_BANDS]
    assert ceilings == sorted(ceilings)
    assert ceilings[-1] == 7
    for days in range(0, 8):
        assert band_for(days) is not None


def test_a_day_beyond_the_table_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        band_for(8)
    with pytest.raises(ValueError):
        band_for(-1)


def test_the_bands_are_data_and_can_be_replaced_without_touching_the_logic():
    # The scheme is reviewed and the reduction is made harsher: every day away
    # now costs an occasion. Nothing but the table changes.
    strict = (
        CountBand(up_to_days_waived=0, reduce_by=0),
        CountBand(up_to_days_waived=1, reduce_by=1),
        CountBand(up_to_days_waived=2, reduce_by=2),
        CountBand(up_to_days_waived=7, waives_entirely=True),
    )
    assert scaled_weekly_count(3, 1, strict) == 2
    assert scaled_weekly_count(3, 2, strict) == 1
    assert scaled_weekly_count(3, 3, strict) == 0

    plan = plan_week(WEEK, [THRICE], day_waivers(MONDAY), bands=strict)
    assert plan.count_for(THRICE.id) == 2


def test_a_reduction_never_takes_a_count_below_zero():
    once = CountBand(up_to_days_waived=7, reduce_by=5)
    assert once.apply(1) == 0


# --- The three cases the card asks for --------------------------------------


def test_a_week_with_no_days_waived():
    plan = plan_week(WEEK, [DAILY, TWICE, THRICE, CONDITION])
    assert plan.days_waived == 0
    assert plan.count_for(DAILY.id) == 7
    assert plan.count_for(TWICE.id) == 2
    assert plan.count_for(THRICE.id) == 3
    assert len(plan.deferred) == 1
    assert len(plan.instances) == 12


def test_a_week_with_three_days_waived():
    plan = plan_week(WEEK, [DAILY, TWICE, THRICE, CONDITION], day_waivers(MONDAY, TUESDAY, WEDNESDAY))
    assert plan.days_waived == 3
    assert plan.count_for(DAILY.id) == 4   # seven days less the three away
    assert plan.count_for(TWICE.id) == 1   # 2x scales to 1x
    assert plan.count_for(THRICE.id) == 2  # 3x scales to 2x
    assert len(plan.deferred) == 1
    assert len(plan.instances) == 7


def test_a_week_with_six_days_waived():
    plan = plan_week(
        WEEK,
        [DAILY, TWICE, THRICE, CONDITION],
        day_waivers(SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY),
    )
    assert plan.days_waived == 6
    assert plan.count_for(DAILY.id) == 1   # only the Saturday remains
    assert plan.count_for(TWICE.id) == 0   # both weekly counts are waived
    assert plan.count_for(THRICE.id) == 0
    assert len(plan.instances) == 1
    assert "scales" in " ".join(exclusion.reason for exclusion in plan.exclusions)


def test_a_fully_waived_week_asks_for_nothing():
    plan = plan_week(WEEK, [DAILY, TWICE, THRICE], day_waivers(*WEEK.days))
    assert plan.days_waived == 7
    assert plan.instances == ()


def test_the_same_day_waived_twice_counts_once():
    waivers = day_waivers(MONDAY) + day_waivers(MONDAY)
    plan = plan_week(WEEK, [THRICE], waivers)
    assert plan.days_waived == 1
    assert plan.count_for(THRICE.id) == 3


# --- Persisting a plan ------------------------------------------------------


def make_rows(session):
    """Real rows, for the sync tests."""
    from app.models import ChoreDefinition, Week

    week_row = Week(start_date=WEEK.start, end_date=WEEK.end)
    daily = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=50
    )
    thrice = ChoreDefinition(
        name="Hoover",
        cadence=Cadence.WEEKLY_COUNT,
        category=Category.BASIC,
        amount_pence=30,
        times_per_week=3,
    )
    session.add_all([week_row, daily, thrice])
    session.commit()
    return week_row, daily, thrice


def test_a_plan_can_be_written_to_the_database(session):
    from app.models import ChoreInstance

    week_row, daily, thrice = make_rows(session)
    plan = plan_week(WEEK, [daily, thrice], week_id=week_row.id)

    created, removed = sync_week_instances(session, week_row, plan)
    session.commit()

    assert (created, removed) == (10, 0)  # seven daily, three hoovering
    stored = session.query(ChoreInstance).all()
    assert len(stored) == 10
    assert all(instance.state is InstanceState.UNTOUCHED for instance in stored)

    # The three week-scoped slots coexist, which the first migration's index
    # would not have allowed.
    week_scoped = [i for i in stored if i.due_date is None]
    assert sorted(i.sequence for i in week_scoped) == [1, 2, 3]


def test_generating_a_week_twice_changes_nothing(session):
    week_row, daily, thrice = make_rows(session)
    plan = plan_week(WEEK, [daily, thrice], week_id=week_row.id)
    sync_week_instances(session, week_row, plan)
    session.commit()

    created, removed = sync_week_instances(session, week_row, plan)
    session.commit()
    assert (created, removed) == (0, 0)


def test_waiving_a_day_afterwards_removes_only_untouched_instances(session):
    from app.models import ChoreInstance

    week_row, daily, _ = make_rows(session)
    sync_week_instances(session, week_row, plan_week(WEEK, [daily], week_id=week_row.id))
    session.commit()

    # The child claims Monday, and a parent confirms it. Then the parent
    # waives Monday and Tuesday after the fact.
    monday = (
        session.query(ChoreInstance).filter(ChoreInstance.due_date == MONDAY).one()
    )
    monday.state = InstanceState.CONFIRMED
    monday.confirmed_at = NOW
    monday.authorised_by = "parent"
    session.commit()

    reduced = plan_week(WEEK, [daily], day_waivers(MONDAY, TUESDAY), week_id=week_row.id)
    created, removed = sync_week_instances(session, week_row, reduced)
    session.commit()

    assert (created, removed) == (0, 1)  # Tuesday went; Monday did not
    remaining = session.query(ChoreInstance).all()
    assert len(remaining) == 6
    survivor = session.query(ChoreInstance).filter(ChoreInstance.due_date == MONDAY).one()
    assert survivor.state is InstanceState.CONFIRMED
