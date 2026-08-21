"""Misses, recovery, and the assignment that pays most.

Money in these tests is always integer pence, and the arithmetic is always
written out, so a wrong answer says what it should have been.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import (
    ON_DEMAND_CADENCES,
    WEEK_DERIVED_CADENCES,
    Cadence,
    Category,
    InstanceState,
    MissOrigin,
)
from app.services.calendar import week_containing
from app.services.instances import plan_week
from app.services.recovery import (
    RECOVERY_CAP,
    all_assignments,
    assess_week,
    best_assignment,
    record_inferred_misses,
)

LONDON = ZoneInfo("Europe/London")
WEEK = week_containing(date(2026, 8, 16), LONDON)
DAYS = WEEK.days


@dataclass
class FakeDefinition:
    id: int
    name: str
    cadence: Cadence
    category: Category
    amount_pence: int
    times_per_week: int | None = None
    weekdays: str | None = None
    is_available: bool = True


@dataclass
class FakeInstance:
    id: int
    definition_id: int
    state: InstanceState
    due_date: date | None = None
    quantity: int = 1


# A week's worth of scheme: seven daily basics worth 350p in total, and three
# bonus chores at different prices.
BEDS = FakeDefinition(1, "Make bed", Cadence.DAILY, Category.BASIC, 350)
HOOVER = FakeDefinition(
    2, "Hoover", Cadence.WEEKLY_COUNT, Category.BONUS, 100, times_per_week=2
)
SHED = FakeDefinition(3, "Clear the shed", Cadence.ONE_OFF, Category.BONUS, 300)
BINS = FakeDefinition(
    4, "Bins", Cadence.WEEKLY_COUNT, Category.BONUS, 200, times_per_week=1
)
TIDY = FakeDefinition(5, "Tidy all week", Cadence.WEEKLY_CONDITION, Category.BONUS, 500)
AWARD = FakeDefinition(6, "School award", Cadence.EVENT, Category.REWARD, 250)
BINS_OUT = FakeDefinition(
    7, "Bins out", Cadence.WEEKDAYS, Category.BONUS, 60, weekdays="tuesday,friday"
)


def instances_for(definition, confirmed=0, missed=0, untouched=0, start=100):
    """Rows for one chore, in the states asked for."""
    rows = []
    number = start
    for _ in range(confirmed):
        rows.append(FakeInstance(number, definition.id, InstanceState.CONFIRMED))
        number += 1
    for _ in range(missed):
        rows.append(FakeInstance(number, definition.id, InstanceState.MISSED))
        number += 1
    for _ in range(untouched):
        rows.append(FakeInstance(number, definition.id, InstanceState.UNTOUCHED))
        number += 1
    return rows


def assess(
    definitions,
    instances,
    waivers=(),
    cap=RECOVERY_CAP,
    weekly_basic_pay_pence=BEDS.amount_pence,
):
    # Defaulted to BEDS's own amount, not because that means anything under
    # the pot model, but because it is what every "350" in this file already
    # expects — one place to keep that true rather than fixture-era numbers
    # scattered through every assertion below.
    plan = plan_week(WEEK, definitions, waivers, week_id=1)
    return assess_week(
        plan,
        definitions,
        instances,
        weekly_basic_pay_pence=weekly_basic_pay_pence,
        cap=cap,
    )


# --- 1. Establishing the week's misses --------------------------------------


def test_a_met_requirement_produces_no_misses():
    assessment = assess([BEDS], instances_for(BEDS, confirmed=7))
    assert assessment.misses == ()
    assert assessment.requirement(BEDS.id).met


def test_an_untouched_instance_becomes_a_miss_only_at_settlement():
    assessment = assess([BEDS], instances_for(BEDS, confirmed=5, untouched=2))
    assert len(assessment.misses) == 2
    assert all(
        miss.origin is MissOrigin.INFERRED_AT_SETTLEMENT for miss in assessment.misses
    )
    assert not any(miss.is_definite for miss in assessment.misses)


def test_a_marked_miss_is_definite_and_keeps_its_origin():
    assessment = assess([BEDS], instances_for(BEDS, confirmed=6, missed=1))
    (miss,) = assessment.misses
    assert miss.origin is MissOrigin.PARENT_MARKED
    assert miss.is_definite


def test_decided_misses_are_named_before_inferred_ones():
    assessment = assess([BEDS], instances_for(BEDS, confirmed=4, missed=1, untouched=2))
    origins = [miss.origin for miss in assessment.misses]
    assert origins == [
        MissOrigin.PARENT_MARKED,
        MissOrigin.INFERRED_AT_SETTLEMENT,
        MissOrigin.INFERRED_AT_SETTLEMENT,
    ]


def test_a_claim_nobody_confirmed_counts_for_nothing():
    rows = instances_for(BEDS, confirmed=6)
    rows.append(FakeInstance(200, BEDS.id, InstanceState.CLAIMED))
    assessment = assess([BEDS], rows)
    assert len(assessment.misses) == 1


# --- The appendment: assess the requirement, never the rows -----------------


def test_a_surplus_confirmed_instance_is_harmless():
    # A waiver applied after the work was confirmed leaves a confirmed row the
    # plan no longer asks for. The requirement was met; that is the whole
    # question, and doing more than was asked cannot hurt.
    from app.models.enums import WaiverScope

    from tests.test_instances import FakeWaiver

    waivers = [FakeWaiver(scope=WaiverScope.DAY, day=DAYS[0])]
    assessment = assess([BEDS], instances_for(BEDS, confirmed=7), waivers)

    requirement = assessment.requirement(BEDS.id)
    assert requirement.required == 6   # the waiver took a day off
    assert requirement.confirmed == 7  # the work was done anyway
    assert requirement.met
    assert requirement.shortfall == 0  # floored, never negative
    assert assessment.misses == ()


def test_a_surplus_cannot_buy_off_a_miss_elsewhere():
    # Seven confirmed against a requirement of six does not leave a spare
    # credit to cover a different chore falling short.
    other = FakeDefinition(9, "Wash up", Cadence.DAILY, Category.BASIC, 70)
    rows = instances_for(BEDS, confirmed=7) + instances_for(
        other, confirmed=6, untouched=1, start=300
    )
    assessment = assess([BEDS, other], rows)
    assert len(assessment.misses) == 1
    assert assessment.misses[0].definition_id == other.id


def test_more_marked_missed_than_the_week_is_short_of_produces_no_extra_miss():
    # A parent marked two missed, then waived a day, so the week only ended up
    # one short. The requirement decides how many misses there are.
    from app.models.enums import WaiverScope

    from tests.test_instances import FakeWaiver

    waivers = [FakeWaiver(scope=WaiverScope.DAY, day=DAYS[0])]
    assessment = assess([BEDS], instances_for(BEDS, confirmed=5, missed=2), waivers)
    assert assessment.requirement(BEDS.id).required == 6
    assert len(assessment.misses) == 1


# --- 2 and 4. Recovering with a completed bonus chore ------------------------


def test_a_completed_bonus_chore_can_recover_a_miss():
    rows = instances_for(BEDS, confirmed=6, untouched=1) + instances_for(
        HOOVER, confirmed=2, start=200
    )
    best = best_assignment(assess([BEDS, HOOVER], rows))

    # The chore pay is rescued, and the bonus is forgone to do it.
    assert best.chore_pay_pence == 350
    assert best.bonus_pay_pence == 0
    assert best.misses_recovered == 1
    assert best.total_pence == 350


def test_a_bonus_chore_is_paid_or_spent_and_never_both():
    rows = instances_for(BEDS, confirmed=7) + instances_for(HOOVER, confirmed=2, start=200)
    assessment = assess([BEDS, HOOVER], rows)
    best = best_assignment(assessment)

    # Nothing to recover, so the bonus is simply paid.
    assert best.spent_definition_ids == ()
    assert best.total_pence == 350 + 100

    # And in every candidate assignment, a spent chore never also pays.
    for assignment in all_assignments(assessment):
        for definition_id in assignment.spent_definition_ids:
            requirement = assessment.requirement(definition_id)
            assert requirement.amount_pence not in (assignment.bonus_pay_pence,)


def test_an_unfinished_bonus_chore_cannot_recover_anything():
    # Hoovering is required twice; one confirmed is not a completed bonus.
    rows = instances_for(BEDS, confirmed=6, untouched=1) + instances_for(
        HOOVER, confirmed=1, untouched=1, start=200
    )
    assessment = assess([BEDS, HOOVER], rows)
    assert assessment.spendable_bonuses == ()

    best = best_assignment(assessment)
    assert best.chore_pay_pence == 0  # the miss stands
    assert best.total_pence == 0


# --- 3. The cap -------------------------------------------------------------


def test_misses_beyond_the_cap_fail_the_chore_pay():
    rows = instances_for(BEDS, confirmed=4, untouched=3) + instances_for(
        HOOVER, confirmed=2, start=200
    ) + instances_for(SHED, confirmed=1, start=300) + instances_for(
        BINS, confirmed=1, start=400
    )
    assessment = assess([BEDS, HOOVER, SHED, BINS], rows)
    assert len(assessment.misses) == 3 > assessment.cap

    best = best_assignment(assessment)
    assert best.chore_pay_pence == 0
    assert best.misses_outstanding == 3
    # And nothing was spent trying: the bonuses are all paid instead.
    assert best.spent_definition_ids == ()
    assert best.bonus_pay_pence == 100 + 300 + 200
    assert best.total_pence == 600


def test_exactly_the_cap_is_still_recoverable():
    # Two misses and two cheap bonuses: 100p + 200p spent rescues 350p, so
    # recovering is worth doing and the cap does not stand in the way.
    rows = instances_for(BEDS, confirmed=5, untouched=2) + instances_for(
        HOOVER, confirmed=2, start=200
    ) + instances_for(BINS, confirmed=1, start=400)
    assessment = assess([BEDS, HOOVER, BINS], rows)
    assert len(assessment.misses) == 2 == assessment.cap

    best = best_assignment(assessment)
    assert best.misses_outstanding == 0
    assert best.chore_pay_pence == 350
    assert best.bonus_pay_pence == 0        # both were spent
    assert best.total_pence == 350          # against 300 for keeping them


def test_recovering_is_not_worth_it_when_the_bonuses_cost_more_than_the_pay():
    # The same two misses, but the bonuses on offer are worth 400p together
    # and the chore pay is 350p. Rescuing it would lose 50p, so it is let go.
    rows = instances_for(BEDS, confirmed=5, untouched=2) + instances_for(
        HOOVER, confirmed=2, start=200
    ) + instances_for(SHED, confirmed=1, start=300)
    assessment = assess([BEDS, HOOVER, SHED], rows)

    best = best_assignment(assessment)
    assert best.spent_definition_ids == ()
    assert best.chore_pay_pence == 0
    assert best.total_pence == 400


def test_the_cap_is_a_number_that_can_be_changed():
    # Three misses, three completed bonuses. Under the cap of two, no lawful
    # assignment can rescue the chore pay at all; raise the cap and one can.
    rows = instances_for(BEDS, confirmed=4, untouched=3) + instances_for(
        HOOVER, confirmed=2, start=200
    ) + instances_for(SHED, confirmed=1, start=300) + instances_for(
        BINS, confirmed=1, start=400
    )
    definitions = [BEDS, HOOVER, SHED, BINS]

    capped = assess(definitions, rows, cap=2)
    assert not any(a.chore_pay_pence for a in all_assignments(capped))

    generous = assess(definitions, rows, cap=3)
    rescued = [a for a in all_assignments(generous) if a.chore_pay_pence == 350]
    assert len(rescued) == 1
    assert rescued[0].misses_outstanding == 0


# --- 6. Eligibility comes from the cadence ----------------------------------


def test_a_cadence_that_cannot_be_done_on_demand_is_not_a_recovery():
    # Tidy-all-week is completed and pays, but it cannot rescue anything: by
    # the time you are told, a week-long condition is already decided.
    rows = instances_for(BEDS, confirmed=6, untouched=1) + instances_for(
        TIDY, confirmed=1, start=200
    )
    assessment = assess([BEDS, TIDY], rows)
    assert [r.name for r in assessment.completed_bonuses] == ["Tidy all week"]
    assert assessment.spendable_bonuses == ()

    best = best_assignment(assessment)
    assert best.chore_pay_pence == 0     # the miss cannot be recovered
    assert best.bonus_pay_pence == 500   # but the condition is still paid
    assert best.total_pence == 500


def test_a_completed_weekdays_bonus_recovers_a_miss_like_a_daily_one():
    # Bins out is due Tuesday and Friday only — plan_week() asks for exactly
    # those two, not seven, and once both are confirmed it is on the same
    # footing as a daily bonus chore: on demand, so spendable.
    rows = instances_for(BEDS, confirmed=6, untouched=1) + instances_for(
        BINS_OUT, confirmed=2
    )
    assessment = assess([BEDS, BINS_OUT], rows)
    assert assessment.requirement(BINS_OUT.id).required == 2  # not 7
    assert [r.name for r in assessment.spendable_bonuses] == [BINS_OUT.name]

    best = best_assignment(assessment)
    assert best.misses_recovered == 1
    assert best.misses_outstanding == 0
    assert best.chore_pay_pence == BEDS.amount_pence  # rescued
    assert best.bonus_pay_pence == 0                  # spent, not paid


def test_eligibility_names_no_chore_anywhere():
    # The rule is a property of the cadence, so a new chore is covered the day
    # it is added without anyone editing the recovery logic.
    assert Cadence.WEEKLY_CONDITION not in ON_DEMAND_CADENCES
    assert Cadence.EVENT not in ON_DEMAND_CADENCES
    assert ON_DEMAND_CADENCES == {
        Cadence.DAILY,
        Cadence.WEEKDAYS,
        Cadence.WEEKLY_COUNT,
        Cadence.ONE_OFF,
    }

    invented = FakeDefinition(
        99, "Something nobody has thought of", Cadence.ONE_OFF, Category.BONUS, 80
    )
    rows = instances_for(BEDS, confirmed=6, untouched=1) + instances_for(
        invented, confirmed=1, start=200
    )
    assessment = assess([BEDS, invented], rows)
    assert [r.name for r in assessment.spendable_bonuses] == [invented.name]


def test_weekdays_is_predictable_from_the_definition_alone():
    # Same footing as DAILY: both are derivable from the definition and the
    # week, so settlement asks the plan how many occasions were wanted rather
    # than counting whatever rows happen to exist.
    assert Cadence.WEEKDAYS in WEEK_DERIVED_CADENCES
    assert WEEK_DERIVED_CADENCES == {
        Cadence.DAILY,
        Cadence.WEEKDAYS,
        Cadence.WEEKLY_COUNT,
        Cadence.WEEKLY_CONDITION,
    }


# --- 6b. The basic chores share one pot, not a sum of their own amounts -----


def test_chore_pay_at_stake_is_the_configured_pot_not_a_sum():
    # Three basic chores, none carrying its own amount any more (all 0),
    # against a pot explicitly set to 200 — the figure must be 200, not the
    # sum of three zeroes and not any of the chores' own retired amount.
    bed = FakeDefinition(20, "Make bed", Cadence.DAILY, Category.BASIC, 0)
    lunchbox = FakeDefinition(21, "Lunchbox and cups", Cadence.DAILY, Category.BASIC, 0)
    hoover = FakeDefinition(
        22, "Hoover", Cadence.WEEKLY_COUNT, Category.BASIC, 0, times_per_week=2
    )
    rows = (
        instances_for(bed, confirmed=7)
        + instances_for(lunchbox, confirmed=7, start=200)
        + instances_for(hoover, confirmed=2, start=300)
    )
    assessment = assess([bed, lunchbox, hoover], rows, weekly_basic_pay_pence=200)
    assert assessment.chore_pay_at_stake_pence == 200


def test_chore_pay_at_stake_is_zero_when_no_basic_chore_is_assessed():
    # Only a bonus chore this week — nothing gates the pot, so it is not at
    # stake at all, whatever it is configured to.
    assessment = assess(
        [HOOVER], instances_for(HOOVER, confirmed=2), weekly_basic_pay_pence=200
    )
    assert assessment.chore_pay_at_stake_pence == 0


def test_chore_pay_at_stake_does_not_grow_with_more_basic_chores():
    # The whole point: adding a second basic chore must not add a second
    # pot's worth on top of the first.
    one = assess([BEDS], instances_for(BEDS, confirmed=7), weekly_basic_pay_pence=200)
    other = FakeDefinition(23, "Wash up", Cadence.DAILY, Category.BASIC, 0)
    two = assess(
        [BEDS, other],
        instances_for(BEDS, confirmed=7) + instances_for(other, confirmed=7, start=200),
        weekly_basic_pay_pence=200,
    )
    assert one.chore_pay_at_stake_pence == two.chore_pay_at_stake_pence == 200


# --- 5. The best assignment, computed --------------------------------------


def greedy(assessment):
    """A plausible wrong answer: recover eagerly, spending the biggest first.

    Written out so the tests can show what the optimiser is beating rather
    than just asserting a number.
    """
    spendable = sorted(
        assessment.spendable_bonuses, key=lambda r: -r.amount_pence
    )
    from app.services.recovery import evaluate

    return evaluate(assessment, spendable[: len(assessment.misses)])


def test_the_greedy_assignment_pays_less_than_the_best_one():
    # One miss, two completed bonuses: a 300p shed and a 100p hoover. Spending
    # the hoover rescues the 350p chore pay and keeps the shed.
    rows = (
        instances_for(BEDS, confirmed=6, untouched=1)
        + instances_for(HOOVER, confirmed=2, start=200)
        + instances_for(SHED, confirmed=1, start=300)
    )
    assessment = assess([BEDS, HOOVER, SHED], rows)

    best = best_assignment(assessment)
    assert best.spent_definition_ids == (HOOVER.id,)
    assert best.chore_pay_pence == 350
    assert best.bonus_pay_pence == 300
    assert best.total_pence == 650

    # The greedy answer rescues the same chore pay and throws away 200p doing it.
    assert greedy(assessment).total_pence == 350 + 100 == 450
    assert best.total_pence - greedy(assessment).total_pence == 200


def test_the_best_answer_is_sometimes_to_recover_nothing():
    # A cheap chore pay and an expensive bonus: rescuing the pay costs more
    # than it is worth, so the bonus is kept and the pay is let go. "Cheap"
    # is now the pot, not the chore's own (retired) amount — set explicitly.
    small = FakeDefinition(10, "Small basics", Cadence.DAILY, Category.BASIC, 50)
    rows = instances_for(small, confirmed=6, untouched=1) + instances_for(
        SHED, confirmed=1, start=300
    )
    assessment = assess([small, SHED], rows, weekly_basic_pay_pence=50)

    best = best_assignment(assessment)
    assert best.spent_definition_ids == ()
    assert best.chore_pay_pence == 0
    assert best.bonus_pay_pence == 300
    assert best.total_pence == 300
    assert greedy(assessment).total_pence == 50


def test_the_optimiser_considers_every_lawful_assignment():
    rows = (
        instances_for(BEDS, confirmed=5, untouched=2)
        + instances_for(HOOVER, confirmed=2, start=200)
        + instances_for(SHED, confirmed=1, start=300)
        + instances_for(BINS, confirmed=1, start=400)
    )
    assessment = assess([BEDS, HOOVER, SHED, BINS], rows)
    assignments = all_assignments(assessment)

    # Nothing spent, each single, and each pair: 1 + 3 + 3.
    assert len(assignments) == 7
    best = best_assignment(assessment)
    assert best.total_pence == max(a.total_pence for a in assignments)

    # Two misses, so the two cheapest bonuses go and the 300p shed is kept.
    assert best.spent_definition_ids == (HOOVER.id, BINS.id)
    assert best.total_pence == 350 + 300


def test_ordering_never_costs_the_child_money():
    # The same week, with the chores presented in every order, settles to the
    # same figure. Recovery is computed, not accumulated as you go.
    import itertools

    rows = (
        instances_for(BEDS, confirmed=6, untouched=1)
        + instances_for(HOOVER, confirmed=2, start=200)
        + instances_for(SHED, confirmed=1, start=300)
    )
    totals = {
        best_assignment(assess(list(order), rows)).total_pence
        for order in itertools.permutations([BEDS, HOOVER, SHED])
    }
    assert totals == {650}


def test_the_best_assignment_is_stable_when_two_are_worth_the_same():
    # Two identically priced bonuses, one miss. Whichever is chosen, the week
    # is worth the same — but it must choose the same one every time, because
    # the figure is about to be stored forever.
    first = FakeDefinition(20, "A chore", Cadence.ONE_OFF, Category.BONUS, 100)
    second = FakeDefinition(21, "B chore", Cadence.ONE_OFF, Category.BONUS, 100)
    rows = (
        instances_for(BEDS, confirmed=6, untouched=1)
        + instances_for(first, confirmed=1, start=200)
        + instances_for(second, confirmed=1, start=300)
    )
    chosen = {
        best_assignment(assess([BEDS, first, second], rows)).spent_definition_ids
        for _ in range(10)
    }
    assert chosen == {(first.id,)}


def test_rewards_are_paid_whatever_the_recovery_does():
    rows = (
        instances_for(BEDS, confirmed=4, untouched=3)
        + instances_for(AWARD, confirmed=1, start=300)
    )
    best = best_assignment(assess([BEDS, AWARD], rows))
    assert best.chore_pay_pence == 0    # three misses, past the cap
    assert best.reward_pence == 250     # earned regardless
    assert best.total_pence == 250


# --- The card's three weeks -------------------------------------------------


def test_more_completed_bonus_chores_than_misses():
    rows = (
        instances_for(BEDS, confirmed=6, untouched=1)          # one miss
        + instances_for(HOOVER, confirmed=2, start=200)        # 100p
        + instances_for(SHED, confirmed=1, start=300)          # 300p
        + instances_for(BINS, confirmed=1, start=400)          # 200p
    )
    assessment = assess([BEDS, HOOVER, SHED, BINS], rows)
    assert len(assessment.misses) == 1
    assert len(assessment.spendable_bonuses) == 3

    best = best_assignment(assessment)
    assert best.spent_definition_ids == (HOOVER.id,)  # the cheapest one goes
    assert best.chore_pay_pence == 350
    assert best.bonus_pay_pence == 300 + 200
    assert best.total_pence == 850


def test_more_misses_than_the_cap():
    rows = (
        instances_for(BEDS, confirmed=3, untouched=4)          # four misses
        + instances_for(HOOVER, confirmed=2, start=200)
        + instances_for(SHED, confirmed=1, start=300)
    )
    assessment = assess([BEDS, HOOVER, SHED], rows)
    assert len(assessment.misses) == 4 > assessment.cap

    best = best_assignment(assessment)
    assert best.chore_pay_pence == 0
    assert best.spent_definition_ids == ()
    assert best.bonus_pay_pence == 100 + 300
    assert best.total_pence == 400


def test_where_the_greedy_assignment_pays_less_than_the_best():
    rows = (
        instances_for(BEDS, confirmed=5, untouched=2)          # two misses
        + instances_for(HOOVER, confirmed=2, start=200)        # 100p
        + instances_for(SHED, confirmed=1, start=300)          # 300p
        + instances_for(BINS, confirmed=1, start=400)          # 200p
    )
    assessment = assess([BEDS, HOOVER, SHED, BINS], rows)

    best = best_assignment(assessment)
    assert best.spent_definition_ids == (HOOVER.id, BINS.id)   # 100p + 200p
    assert best.total_pence == 350 + 300

    # Greedy spends the shed and the bins, keeping the cheapest.
    assert greedy(assessment).total_pence == 350 + 100
    assert best.total_pence > greedy(assessment).total_pence


# --- Writing the inferred misses -------------------------------------------


def test_an_inferred_miss_is_written_without_an_author(session):
    from app.models import Cadence as C
    from app.models import Category as Cat
    from app.models import ChoreDefinition, ChoreInstance, Week

    week = Week(start_date=WEEK.start, end_date=WEEK.end)
    definition = ChoreDefinition(
        name="Make bed", cadence=C.DAILY, category=Cat.BASIC, amount_pence=350
    )
    session.add_all([week, definition])
    session.commit()

    for day in DAYS:
        session.add(
            ChoreInstance(definition_id=definition.id, week_id=week.id, due_date=day)
        )
    session.commit()

    plan = plan_week(WEEK, [definition], week_id=week.id)
    assessment = assess_week(plan, [definition], week.instances, weekly_basic_pay_pence=350)
    assert len(assessment.misses) == 7

    written = record_inferred_misses(session, assessment.misses)
    session.commit()
    assert written == 7

    session.expire_all()
    for instance in session.get(Week, week.id).instances:
        assert instance.state is InstanceState.MISSED
        assert instance.miss_origin is MissOrigin.INFERRED_AT_SETTLEMENT
        # Nobody decided this, so nobody is named for it.
        assert instance.authorised_by is None


def test_an_inferred_miss_does_not_inherit_the_name_of_whoever_rejected(session):
    # The child claimed, a parent rejected it, and nothing happened after. The
    # parent refused a claim; they did not rule the chore missed, and the
    # record must not read as though they had.
    from app.models import Cadence as C
    from app.models import Category as Cat
    from app.models import ChoreDefinition, ChoreInstance, Week

    week = Week(start_date=WEEK.start, end_date=WEEK.end)
    definition = ChoreDefinition(
        name="Make bed", cadence=C.DAILY, category=Cat.BASIC, amount_pence=350
    )
    session.add_all([week, definition])
    session.commit()

    instance = ChoreInstance(
        definition_id=definition.id,
        week_id=week.id,
        due_date=DAYS[0],
        authorised_by="parent",   # left over from rejecting the claim
        rejected_at=week.created_at,
        rejection_count=1,
    )
    session.add(instance)
    session.commit()

    plan = plan_week(WEEK, [definition], week_id=week.id)
    assessment = assess_week(plan, [definition], [instance], weekly_basic_pay_pence=350)
    record_inferred_misses(session, assessment.misses)
    session.commit()
    session.expire_all()

    stored = session.get(ChoreInstance, instance.id)
    assert stored.miss_origin is MissOrigin.INFERRED_AT_SETTLEMENT
    assert stored.authorised_by is None    # not the rejecting parent
    assert stored.rejection_count == 1     # the rejection itself still stands


def test_the_database_refuses_an_inferred_miss_with_an_author(session):
    from sqlalchemy.exc import IntegrityError

    from app.models import Cadence as C
    from app.models import Category as Cat
    from app.models import ChoreDefinition, ChoreInstance, Week

    week = Week(start_date=WEEK.start, end_date=WEEK.end)
    definition = ChoreDefinition(
        name="Make bed", cadence=C.DAILY, category=Cat.BASIC, amount_pence=350
    )
    session.add_all([week, definition])
    session.commit()

    session.add(
        ChoreInstance(
            definition_id=definition.id,
            week_id=week.id,
            due_date=DAYS[0],
            state=InstanceState.MISSED,
            missed_at=week.created_at,
            miss_origin=MissOrigin.INFERRED_AT_SETTLEMENT,
            authorised_by="parent",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_a_miss_must_say_how_it_arose(session):
    from sqlalchemy.exc import IntegrityError

    from app.models import Cadence as C
    from app.models import Category as Cat
    from app.models import ChoreDefinition, ChoreInstance, Week

    week = Week(start_date=WEEK.start, end_date=WEEK.end)
    definition = ChoreDefinition(
        name="Make bed", cadence=C.DAILY, category=Cat.BASIC, amount_pence=350
    )
    session.add_all([week, definition])
    session.commit()

    session.add(
        ChoreInstance(
            definition_id=definition.id,
            week_id=week.id,
            due_date=DAYS[0],
            state=InstanceState.MISSED,
            missed_at=week.created_at,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
