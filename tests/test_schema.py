"""The schema, exercised through the real migration.

The first test group runs the migration against an empty file. The rest use
that database, so every constraint and trigger asserted here is one that will
exist on the Pi, not one that only exists in the models.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import (
    Cadence,
    Category,
    ChoreDefinition,
    ChoreInstance,
    EarningEntry,
    EarningType,
    InstanceState,
    SavingsEntry,
    SavingsType,
    SettlementLine,
    Waiver,
    WaiverScope,
    Week,
    WeekStatus,
)

SUNDAY = date(2026, 8, 16)
SATURDAY = date(2026, 8, 22)
NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)

EXPECTED_TABLES = {
    "chore_definitions",
    "chore_instances",
    "weeks",
    "settlement_lines",
    "waivers",
    "earnings_ledger",
    "savings_ledger",
}


# --- The migration itself --------------------------------------------------


def test_the_migration_runs_against_an_empty_database(session):
    found = {
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
    }
    assert EXPECTED_TABLES <= found


def test_the_migration_installs_the_immutability_triggers(session):
    triggers = {
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        )
    }
    assert {
        "settled_week_figures_are_final",
        "settlement_lines_are_not_updated",
        "settlement_lines_are_not_deleted",
        "earnings_are_not_updated",
        "earnings_are_not_deleted",
        "savings_are_not_updated",
        "savings_are_not_deleted",
    } <= triggers


def test_foreign_keys_are_enforced(session):
    # Off by default in SQLite, which would silently disable every ON DELETE
    # RESTRICT in the schema.
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


# --- Helpers ---------------------------------------------------------------


def make_definition(session, **overrides) -> ChoreDefinition:
    values = {
        "name": "Wash up",
        "cadence": Cadence.DAILY,
        "category": Category.BASIC,
        "amount_pence": 50,
    }
    values.update(overrides)
    definition = ChoreDefinition(**values)
    session.add(definition)
    session.commit()
    return definition


def make_week(session, start=SUNDAY, end=SATURDAY) -> Week:
    week = Week(start_date=start, end_date=end)
    session.add(week)
    session.commit()
    return week


def settle(session, week: Week, definition: ChoreDefinition) -> None:
    """Close a week, copying the chore's figures into a settlement line."""
    session.add(
        SettlementLine(
            week_id=week.id,
            chore_name=definition.name,        # a copy, taken now
            category=definition.category,
            cadence=definition.cadence,
            unit_amount_pence=definition.amount_pence,
            quantity=7,
            amount_pence=definition.amount_pence * 7,
            source_definition_id=definition.id,  # provenance only
        )
    )
    week.status = WeekStatus.SETTLED
    week.settled_basic_pence = definition.amount_pence * 7
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = definition.amount_pence * 7
    week.closed_at = NOW
    session.commit()


# --- The rule this session exists for --------------------------------------


def test_changing_a_definition_leaves_a_settled_week_untouched(session):
    definition = make_definition(session, name="Wash up", amount_pence=50)
    week = make_week(session)
    settle(session, week, definition)
    assert week.settled_total_pence == 350

    # The scheme is reviewed and the chore is rewritten: renamed, repriced,
    # recategorised, and withdrawn from use altogether.
    definition.name = "Wash up and put away"
    definition.amount_pence = 125
    definition.category = Category.BONUS
    definition.is_available = False
    session.commit()
    session.expire_all()

    # Not one figure in the closed week has moved.
    week = session.get(Week, week.id)
    assert week.settled_basic_pence == 350
    assert week.settled_total_pence == 350

    (line,) = week.settlement_lines
    assert line.chore_name == "Wash up"          # the name as it read that week
    assert line.unit_amount_pence == 50          # the amount as it stood
    assert line.category is Category.BASIC       # the category as it was
    assert line.amount_pence == 350

    # And the definition really did change underneath it.
    assert definition.name == "Wash up and put away"
    assert definition.amount_pence == 125


def test_a_settled_week_survives_the_definition_being_deleted(session):
    definition = make_definition(session, amount_pence=50)
    week = make_week(session)
    settle(session, week, definition)

    # Deleting a definition is not something the app offers, but the schema
    # must not let it destroy history if it ever happened.
    session.delete(definition)
    session.commit()
    session.expire_all()

    (line,) = session.get(Week, week.id).settlement_lines
    assert line.source_definition_id is None  # provenance gone...
    assert line.chore_name == "Wash up"       # ...the money and the story remain
    assert line.unit_amount_pence == 50
    assert line.amount_pence == 350
    assert session.get(Week, week.id).settled_total_pence == 350


def test_a_settled_weeks_figures_cannot_be_updated(session):
    definition = make_definition(session)
    week = make_week(session)
    settle(session, week, definition)

    with pytest.raises((IntegrityError, OperationalError), match="closed forever"):
        session.execute(
            text("UPDATE weeks SET settled_total_pence = 9999 WHERE id = :id"),
            {"id": week.id},
        )
    session.rollback()
    assert session.get(Week, week.id).settled_total_pence == 350


def test_a_settled_week_cannot_be_reopened(session):
    definition = make_definition(session)
    week = make_week(session)
    settle(session, week, definition)

    with pytest.raises((IntegrityError, OperationalError), match="closed forever"):
        session.execute(
            text("UPDATE weeks SET status = 'open' WHERE id = :id"), {"id": week.id}
        )
    session.rollback()


def test_payday_may_still_be_recorded_against_a_settled_week(session):
    # The one thing that must stay writable after settlement: the week was
    # settled on Sunday and paid later, with part of it deposited.
    definition = make_definition(session)
    week = make_week(session)
    settle(session, week, definition)

    week.paid_at = NOW
    week.deposited_pence = 200
    session.commit()
    session.expire_all()

    assert session.get(Week, week.id).deposited_pence == 200
    assert session.get(Week, week.id).settled_total_pence == 350


def test_a_settlement_line_cannot_be_edited_or_deleted(session):
    definition = make_definition(session)
    week = make_week(session)
    settle(session, week, definition)
    (line,) = week.settlement_lines

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(
            text("UPDATE settlement_lines SET amount_pence = 1 WHERE id = :id"),
            {"id": line.id},
        )
    session.rollback()

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(
            text("DELETE FROM settlement_lines WHERE id = :id"), {"id": line.id}
        )
    session.rollback()


def test_a_voided_week_pays_nothing_but_keeps_its_instances(session):
    definition = make_definition(session)
    week = make_week(session)
    session.add(
        ChoreInstance(
            definition_id=definition.id,
            week_id=week.id,
            due_date=SUNDAY,
            state=InstanceState.CONFIRMED,
            confirmed_at=NOW,
        )
    )
    session.commit()

    week.status = WeekStatus.VOIDED
    week.void_reason = "Away all week"
    week.settled_basic_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 0
    week.closed_at = NOW
    session.commit()
    session.expire_all()

    week = session.get(Week, week.id)
    assert week.settled_total_pence == 0
    assert len(week.instances) == 1  # the record of the work done survives
    assert week.instances[0].state is InstanceState.CONFIRMED


def test_a_voided_week_may_not_pay_anything(session):
    week = make_week(session)
    week.status = WeekStatus.VOIDED
    week.settled_basic_pence = 100
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 100
    week.closed_at = NOW
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- Weeks -----------------------------------------------------------------


def test_a_week_must_start_on_a_sunday(session):
    with pytest.raises(IntegrityError):
        session.add(Week(start_date=date(2026, 8, 17), end_date=date(2026, 8, 23)))
        session.commit()
    session.rollback()


def test_a_week_must_run_seven_days(session):
    with pytest.raises(IntegrityError):
        session.add(Week(start_date=SUNDAY, end_date=date(2026, 8, 21)))
        session.commit()
    session.rollback()


def test_a_week_starts_open_with_no_figures(session):
    week = make_week(session)
    assert week.status is WeekStatus.OPEN
    assert week.settled_total_pence is None
    assert week.closed_at is None
    assert not week.is_closed


def test_an_open_week_may_not_carry_figures(session):
    week = Week(start_date=SUNDAY, end_date=SATURDAY, settled_total_pence=100)
    with pytest.raises(IntegrityError):
        session.add(week)
        session.commit()
    session.rollback()


def test_a_closed_week_totals_must_add_up(session):
    week = make_week(session)
    week.status = WeekStatus.SETTLED
    week.settled_basic_pence = 100
    week.settled_bonus_pence = 50
    week.settled_reward_pence = 0
    week.settled_total_pence = 200  # not 150
    week.closed_at = NOW
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_more_than_one_week_may_be_open_at_once(session):
    first = make_week(session)
    second = make_week(session, start=date(2026, 8, 23), end=date(2026, 8, 29))
    assert first.status is second.status is WeekStatus.OPEN


def test_a_week_starts_only_once(session):
    make_week(session)
    with pytest.raises(IntegrityError):
        make_week(session)
    session.rollback()


def test_a_deposit_cannot_exceed_the_payment(session):
    definition = make_definition(session)
    week = make_week(session)
    settle(session, week, definition)
    week.deposited_pence = 400  # the week only paid 350
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- Definitions and instances ---------------------------------------------


def test_no_amount_in_the_scheme_is_negative(session):
    # There are no fines and no deductions of any kind.
    with pytest.raises(IntegrityError):
        make_definition(session, name="Fine", amount_pence=-100)
    session.rollback()


def test_a_weekly_count_chore_states_how_many(session):
    with pytest.raises(IntegrityError):
        make_definition(session, name="Bins", cadence=Cadence.WEEKLY_COUNT)
    session.rollback()


def test_only_a_weekly_count_chore_states_how_many(session):
    with pytest.raises(IntegrityError):
        make_definition(session, name="Bins", cadence=Cadence.DAILY, times_per_week=3)
    session.rollback()


def test_a_weekly_count_chore_is_accepted_with_its_count(session):
    definition = make_definition(
        session, name="Bins", cadence=Cadence.WEEKLY_COUNT, times_per_week=3
    )
    assert definition.times_per_week == 3


def test_a_withdrawn_chore_is_switched_off_not_deleted(session):
    definition = make_definition(session)
    assert definition.is_available is True
    definition.is_available = False
    session.commit()
    assert session.get(ChoreDefinition, definition.id).is_available is False


def test_a_definition_with_instances_cannot_be_deleted(session):
    definition = make_definition(session)
    week = make_week(session)
    session.add(
        ChoreInstance(definition_id=definition.id, week_id=week.id, due_date=SUNDAY)
    )
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM chore_definitions WHERE id = :id"), {"id": definition.id}
        )
        session.commit()
    session.rollback()


def test_an_instance_starts_untouched(session):
    definition = make_definition(session)
    week = make_week(session)
    instance = ChoreInstance(
        definition_id=definition.id, week_id=week.id, due_date=SUNDAY
    )
    session.add(instance)
    session.commit()
    # Provisional: it becomes a miss only at settlement.
    assert instance.state is InstanceState.UNTOUCHED
    assert instance.missed_at is None


def test_a_claimed_instance_records_when_it_was_claimed(session):
    definition = make_definition(session)
    week = make_week(session)
    instance = ChoreInstance(
        definition_id=definition.id,
        week_id=week.id,
        due_date=SUNDAY,
        state=InstanceState.CLAIMED,
    )
    with pytest.raises(IntegrityError):  # no claimed_at
        session.add(instance)
        session.commit()
    session.rollback()


def test_a_day_chore_gets_one_instance_per_day(session):
    definition = make_definition(session)
    week = make_week(session)
    session.add(
        ChoreInstance(definition_id=definition.id, week_id=week.id, due_date=SUNDAY)
    )
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(
            ChoreInstance(definition_id=definition.id, week_id=week.id, due_date=SUNDAY)
        )
        session.commit()
    session.rollback()


def test_a_week_scoped_chore_gets_one_instance_per_slot(session):
    definition = make_definition(
        session, name="Room tidy all week", cadence=Cadence.WEEKLY_CONDITION
    )
    week = make_week(session)
    session.add(
        ChoreInstance(definition_id=definition.id, week_id=week.id, due_date=None)
    )
    session.commit()
    with pytest.raises(IntegrityError):  # slot 1 twice
        session.add(
            ChoreInstance(definition_id=definition.id, week_id=week.id, due_date=None)
        )
        session.commit()
    session.rollback()


def test_a_weekly_count_chore_may_hold_several_slots_in_one_week(session):
    # Three separately claimable occasions, numbered. The first migration
    # allowed only one, which was right for a condition and wrong for a count.
    definition = make_definition(
        session, name="Hoover", cadence=Cadence.WEEKLY_COUNT, times_per_week=3
    )
    week = make_week(session)
    for slot in (1, 2, 3):
        session.add(
            ChoreInstance(
                definition_id=definition.id,
                week_id=week.id,
                due_date=None,
                sequence=slot,
            )
        )
    session.commit()
    assert len(week.instances) == 3


# --- Waivers ---------------------------------------------------------------


def test_a_day_may_be_waived(session):
    waiver = Waiver(scope=WaiverScope.DAY, day=SUNDAY, reason="Away")
    session.add(waiver)
    session.commit()
    assert waiver.id is not None


def test_a_chore_may_be_waived_for_a_week(session):
    definition = make_definition(session)
    week = make_week(session)
    waiver = Waiver(
        scope=WaiverScope.CHORE_WEEK,
        week_id=week.id,
        definition_id=definition.id,
        reason="Bin collection cancelled",
    )
    session.add(waiver)
    session.commit()
    assert waiver.week_id == week.id


def test_a_day_waiver_may_not_name_a_chore(session):
    definition = make_definition(session)
    with pytest.raises(IntegrityError):
        session.add(
            Waiver(scope=WaiverScope.DAY, day=SUNDAY, definition_id=definition.id)
        )
        session.commit()
    session.rollback()


def test_a_chore_week_waiver_must_name_both(session):
    week = make_week(session)
    with pytest.raises(IntegrityError):
        session.add(Waiver(scope=WaiverScope.CHORE_WEEK, week_id=week.id))
        session.commit()
    session.rollback()


def test_a_day_is_waived_only_once(session):
    session.add(Waiver(scope=WaiverScope.DAY, day=SUNDAY))
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(Waiver(scope=WaiverScope.DAY, day=SUNDAY))
        session.commit()
    session.rollback()


# --- The ledgers -----------------------------------------------------------


def test_the_earnings_ledger_is_append_only(session):
    week = make_week(session)
    entry = EarningEntry(
        entry_type=EarningType.WEEK_SETTLEMENT,
        amount_pence=350,
        week_id=week.id,
        occurred_on=SUNDAY,
    )
    session.add(entry)
    session.commit()

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(
            text("UPDATE earnings_ledger SET amount_pence = 1 WHERE id = :id"),
            {"id": entry.id},
        )
    session.rollback()

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(
            text("DELETE FROM earnings_ledger WHERE id = :id"), {"id": entry.id}
        )
    session.rollback()

    assert session.get(EarningEntry, entry.id).amount_pence == 350


def test_a_reward_must_say_why(session):
    with pytest.raises(IntegrityError):
        session.add(
            EarningEntry(
                entry_type=EarningType.REWARD, amount_pence=200, occurred_on=SUNDAY
            )
        )
        session.commit()
    session.rollback()


def test_a_reward_with_a_reason_is_accepted(session):
    entry = EarningEntry(
        entry_type=EarningType.REWARD,
        amount_pence=200,
        occurred_on=SUNDAY,
        reason="Headteacher's award",
    )
    session.add(entry)
    session.commit()
    assert entry.amount_pence == 200


def test_the_earnings_ledger_never_goes_negative(session):
    with pytest.raises(IntegrityError):
        session.add(
            EarningEntry(
                entry_type=EarningType.REWARD,
                amount_pence=-100,
                occurred_on=SUNDAY,
                reason="A fine, which this scheme does not have",
            )
        )
        session.commit()
    session.rollback()


def test_the_savings_ledger_is_append_only(session):
    entry = SavingsEntry(
        entry_type=SavingsType.OPENING_BALANCE,
        amount_pence=1500,
        balance_after_pence=1500,
        occurred_on=SUNDAY,
    )
    session.add(entry)
    session.commit()

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(
            text("UPDATE savings_ledger SET balance_after_pence = 0 WHERE id = :id"),
            {"id": entry.id},
        )
    session.rollback()
    assert session.get(SavingsEntry, entry.id).balance_after_pence == 1500


def test_a_savings_run_keeps_its_own_running_balance(session):
    week = make_week(session)
    opening = SavingsEntry(
        entry_type=SavingsType.OPENING_BALANCE,
        amount_pence=1500,
        balance_after_pence=1500,
        occurred_on=SUNDAY,
    )
    deposit = SavingsEntry(
        entry_type=SavingsType.DEPOSIT,
        amount_pence=200,
        balance_after_pence=1700,
        week_id=week.id,
        occurred_on=SUNDAY,
    )
    withdrawal = SavingsEntry(
        entry_type=SavingsType.WITHDRAWAL,
        amount_pence=-500,
        balance_after_pence=1200,
        occurred_on=SATURDAY,
        reason="Bought a game",
    )
    session.add_all([opening, deposit, withdrawal])
    session.commit()

    entries = session.query(SavingsEntry).order_by(SavingsEntry.id).all()
    assert [entry.amount_pence for entry in entries] == [1500, 200, -500]
    assert entries[-1].balance_after_pence == 1200
    # Every figure is an integer number of pence.
    assert all(isinstance(entry.amount_pence, int) for entry in entries)


def test_only_a_withdrawal_may_be_negative(session):
    with pytest.raises(IntegrityError):
        session.add(
            SavingsEntry(
                entry_type=SavingsType.DEPOSIT,
                amount_pence=-100,
                balance_after_pence=0,
                occurred_on=SUNDAY,
            )
        )
        session.commit()
    session.rollback()


def test_the_savings_balance_cannot_go_overdrawn(session):
    with pytest.raises(IntegrityError):
        session.add(
            SavingsEntry(
                entry_type=SavingsType.WITHDRAWAL,
                amount_pence=-100,
                balance_after_pence=-100,
                occurred_on=SUNDAY,
            )
        )
        session.commit()
    session.rollback()


# --- Instants --------------------------------------------------------------


def test_instants_are_stored_as_utc_and_come_back_aware(session):
    definition = make_definition(session)
    week = make_week(session)
    settle(session, week, definition)
    session.expire_all()

    closed_at = session.get(Week, week.id).closed_at
    assert closed_at.tzinfo is not None
    assert closed_at == NOW


def test_a_naive_instant_is_refused(session):
    week = make_week(session)
    week.status = WeekStatus.SETTLED
    week.settled_basic_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 0
    week.closed_at = datetime(2026, 8, 23, 9, 0)  # no zone
    with pytest.raises(Exception, match="naive"):
        session.commit()
    session.rollback()


def test_provenance_may_be_cleared_but_never_repointed(session):
    # The one update a settlement line permits is ON DELETE SET NULL severing
    # its provenance. Pointing it at a different chore is not a correction, it
    # is a rewrite of what happened.
    definition = make_definition(session)
    other = make_definition(session, name="Something else")
    week = make_week(session)
    settle(session, week, definition)
    (line,) = week.settlement_lines

    with pytest.raises((IntegrityError, OperationalError), match="append-only"):
        session.execute(
            text(
                "UPDATE settlement_lines SET source_definition_id = :other"
                " WHERE id = :id"
            ),
            {"other": other.id, "id": line.id},
        )
    session.rollback()
