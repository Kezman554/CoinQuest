"""Reopening a settled week: a parent's own mistake, undone narrowly.

"A settled week is a closed event" still holds. This is the one controlled
exception to it — for a figure agreed on purpose and later regretted, never
for a scheme change reaching backwards. Every test here proves the exception
stays narrow: only the latest settled week, only with a reason, the payment
unwound by a reversal rather than an edit, and re-settling through the
ordinary path with no shortcut.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import (
    Cadence,
    Category,
    ChoreDefinition,
    ChoreInstance,
    InstanceState,
    MissOrigin,
    SavingsEntry,
    SavingsType,
    Week,
    WeekReopening,
    WeekStatus,
)
from app.services import scheme_settings, settlement
from app.services.authorisation import Authorisation
from app.services.authorisation import PARENT as PARENT_PARTY

PIN = "0000"
WRONG = "9999"
FIRST_SUNDAY = date(2026, 8, 16)
FIRST_SATURDAY = date(2026, 8, 22)
SECOND_SUNDAY = date(2026, 8, 23)
SECOND_SATURDAY = date(2026, 8, 29)
PAYDAY = date(2026, 8, 30)


@pytest.fixture()
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def beds(session) -> ChoreDefinition:
    definition = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=0
    )
    session.add(definition)
    scheme_settings.get_row(session).weekly_basic_pay_pence = 350
    session.commit()
    return definition


def _week_with_instances(
    session, beds, start, end, *, confirmed: int = 7
) -> Week:
    week = Week(start_date=start, end_date=end)
    session.add(week)
    session.commit()

    for offset in range(7):
        state = InstanceState.CONFIRMED if offset < confirmed else InstanceState.UNTOUCHED
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(start.toordinal() + offset),
                state=state,
                confirmed_at=week.created_at if state is InstanceState.CONFIRMED else None,
                authorised_by="parent" if state is InstanceState.CONFIRMED else None,
            )
        )
    session.commit()
    return week


def settled_week(api, session, beds, start=FIRST_SUNDAY, end=FIRST_SATURDAY) -> Week:
    """A perfect week, settled. Worth 100p base + 350p chore pay = 450p."""
    week = _week_with_instances(session, beds, start, end, confirmed=7)
    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert proposal["total_pence"] == 450
    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert response.status_code == 200
    return week


def paid_week(api, session, beds, start=FIRST_SUNDAY, end=FIRST_SATURDAY, deposit=450) -> Week:
    week = settled_week(api, session, beds, start, end)
    response = api.post(
        "/api/weeks/payments",
        json={
            "pin": PIN,
            "week_ids": [week.id],
            "deposited_pence": deposit,
            "occurred_on": PAYDAY.isoformat(),
        },
    )
    assert response.status_code == 200
    return week


# --- 1. The full round trip --------------------------------------------------


def test_settle_pay_reopen_change_resettle(api, session, beds):
    """The card's own test: settle, pay, reopen, change a confirmation, resettle."""
    week = paid_week(api, session, beds, deposit=450)
    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.SETTLED
    assert session.query(SavingsEntry).count() == 1
    assert session.query(SavingsEntry).one().balance_after_pence == 450

    response = api.post(
        f"/api/weeks/{week.id}/reopen",
        json={"pin": PIN, "reason": "Confirmed a claim that was not actually done"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "open"

    # The week is open again, with none of its closing figures left over.
    session.expire_all()
    reopened = session.get(Week, week.id)
    assert reopened.status is WeekStatus.OPEN
    assert reopened.settled_total_pence is None
    assert reopened.settled_base_pence is None
    assert reopened.closed_at is None
    assert reopened.paid_at is None
    assert reopened.deposited_pence is None

    # The payment is unwound by a reversal entry, not an edit to the deposit.
    entries = session.query(SavingsEntry).order_by(SavingsEntry.id).all()
    assert len(entries) == 2
    deposit, reversal = entries
    assert deposit.amount_pence == 450          # untouched, exactly as written
    assert deposit.entry_type is SavingsType.DEPOSIT
    assert reversal.entry_type is SavingsType.REVERSAL
    assert reversal.amount_pence == -450
    assert reversal.balance_after_pence == 0
    assert reversal.week_id == week.id

    # The savings balance is back to what it was before the payment.
    assert api.get("/api/savings").json()["balance_pence"] == 0

    # The reopening itself is recorded: who, when, why, what it undid.
    (reopening,) = session.query(WeekReopening).all()
    assert reopening.week_id == week.id
    assert reopening.reopened_by == "parent"
    assert reopening.reason == "Confirmed a claim that was not actually done"
    assert reopening.previous_total_pence == 450
    assert reopening.was_paid is True
    assert reopening.reversed_deposit_pence == 450

    # A confirmation changes: one basic instance was wrongly confirmed and is
    # put right — corrected by un-confirming it and marking it missed. The
    # week does not settle the same way twice.
    instance = (
        session.query(ChoreInstance)
        .filter(ChoreInstance.week_id == week.id)
        .order_by(ChoreInstance.due_date)
        .first()
    )
    instance.state = InstanceState.MISSED
    instance.confirmed_at = None
    instance.missed_at = reopened.created_at
    instance.miss_origin = MissOrigin.PARENT_MARKED
    instance.authorised_by = "parent"
    session.commit()

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert proposal["total_pence"] < 450  # the pot is no longer earned outright

    resettled = api.post(
        f"/api/weeks/{week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": proposal["total_pence"]},
    )
    assert resettled.status_code == 200
    final = resettled.json()
    assert final["status"] == "settled"
    assert final["total_pence"] == proposal["total_pence"]
    assert final["total_pence"] != 450

    # History survives: the reopening is still there, alongside a fresh
    # earnings-ledger settlement entry for the new figure.
    assert len(final["reopenings"]) == 1
    assert final["reopenings"][0]["previous_total_pence"] == 450

    session.expire_all()
    settlements = session.query(WeekReopening).count()
    assert settlements == 1  # one reopening recorded, not erased and not doubled


def test_a_settled_but_unpaid_week_reopens_without_touching_savings(api, session, beds):
    week = settled_week(api, session, beds)
    assert session.query(SavingsEntry).count() == 0

    response = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Wrong figure agreed"}
    )
    assert response.status_code == 200
    assert session.query(SavingsEntry).count() == 0

    (reopening,) = session.query(WeekReopening).all()
    assert reopening.was_paid is False
    assert reopening.reversed_deposit_pence == 0
    assert reopening.reversal_entry_id is None


def test_only_the_apportioned_share_is_reversed(api, session, beds):
    """One payment clears two weeks; reopening the later one reverses only
    the share that payment apportioned to it, not the whole payment."""
    first = settled_week(api, session, beds, FIRST_SUNDAY, FIRST_SATURDAY)
    second = settled_week(api, session, beds, SECOND_SUNDAY, SECOND_SATURDAY)

    response = api.post(
        "/api/weeks/payments",
        json={
            "pin": PIN,
            "week_ids": [first.id, second.id],
            "deposited_pence": 500,  # 450 to `first`, 50 to `second`
            "occurred_on": PAYDAY.isoformat(),
        },
    )
    assert response.status_code == 200
    assert api.get("/api/savings").json()["balance_pence"] == 500

    # `first` cannot be reopened: `second` settled after it.
    blocked = api.post(
        f"/api/weeks/{first.id}/reopen", json={"pin": PIN, "reason": "Second thoughts"}
    )
    assert blocked.status_code == 409

    # `second` can — it is the latest settled week.
    reopened = api.post(
        f"/api/weeks/{second.id}/reopen", json={"pin": PIN, "reason": "Second thoughts"}
    )
    assert reopened.status_code == 200

    # Only its 50p share came back out, not the whole 500p payment.
    assert api.get("/api/savings").json()["balance_pence"] == 450
    session.expire_all()
    assert session.get(Week, first.id).deposited_pence == 450  # untouched
    assert session.get(Week, first.id).status is WeekStatus.SETTLED
    assert session.get(Week, second.id).paid_at is None
    assert session.get(Week, second.id).deposited_pence is None


def test_a_reopen_that_would_overdraw_savings_is_refused(api, session, beds):
    week = paid_week(api, session, beds, deposit=450)
    # The child spends some of it before anyone notices the mistake.
    withdrawal = api.post(
        "/api/savings/withdrawals",
        json={"pin": PIN, "amount_pence": 400, "reason": "New game"},
    )
    assert withdrawal.status_code == 201
    assert api.get("/api/savings").json()["balance_pence"] == 50

    response = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Wrong figure"}
    )
    assert response.status_code == 409

    # Nothing was applied: the week is still settled and paid, the balance
    # untouched.
    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.SETTLED
    assert session.get(Week, week.id).paid_at is not None
    assert api.get("/api/savings").json()["balance_pence"] == 50
    assert session.query(WeekReopening).count() == 0


# --- 2. Only the most recent settled week -----------------------------------


def test_an_earlier_settled_week_cannot_be_reopened_via_the_endpoint(api, session, beds):
    first = settled_week(api, session, beds, FIRST_SUNDAY, FIRST_SATURDAY)
    settled_week(api, session, beds, SECOND_SUNDAY, SECOND_SATURDAY)

    response = api.post(
        f"/api/weeks/{first.id}/reopen", json={"pin": PIN, "reason": "Changed my mind"}
    )
    assert response.status_code == 409
    assert "settled after this one" in response.json()["detail"]

    session.expire_all()
    assert session.get(Week, first.id).status is WeekStatus.SETTLED


def test_an_earlier_settled_week_cannot_be_reopened_via_the_routine(api, session, beds):
    """The same discipline as the closed-week guard: enforced in the routine
    itself, not only at the endpoint, so nothing can route around it."""
    first = settled_week(api, session, beds, FIRST_SUNDAY, FIRST_SATURDAY)
    settled_week(api, session, beds, SECOND_SUNDAY, SECOND_SATURDAY)

    authorisation = Authorisation(party=PARENT_PARTY, at=session.get(Week, first.id).created_at)
    with pytest.raises(settlement.NotTheLatestSettledWeek):
        settlement.reopen(session, first, authorisation, reason="Changed my mind")

    session.rollback()
    assert session.get(Week, first.id).status is WeekStatus.SETTLED


def test_the_latest_settled_week_reopens_once_the_one_after_it_is_reopened(api, session, beds):
    """Reopen the later week first; the earlier one is then eligible."""
    first = settled_week(api, session, beds, FIRST_SUNDAY, FIRST_SATURDAY)
    second = settled_week(api, session, beds, SECOND_SUNDAY, SECOND_SATURDAY)

    assert api.post(
        f"/api/weeks/{second.id}/reopen", json={"pin": PIN, "reason": "Wrong figure"}
    ).status_code == 200

    # `second` is open now, not settled, so it no longer blocks `first`.
    response = api.post(
        f"/api/weeks/{first.id}/reopen", json={"pin": PIN, "reason": "This one too"}
    )
    assert response.status_code == 200


def test_a_voided_week_after_it_also_blocks_reopening(api, session, beds):
    first = settled_week(api, session, beds, FIRST_SUNDAY, FIRST_SATURDAY)
    later = Week(start_date=SECOND_SUNDAY, end_date=SECOND_SATURDAY)
    session.add(later)
    session.commit()
    void = api.post(f"/api/weeks/{later.id}/void", json={"pin": PIN, "reason": "Away"})
    assert void.status_code == 200

    response = api.post(
        f"/api/weeks/{first.id}/reopen", json={"pin": PIN, "reason": "Changed my mind"}
    )
    assert response.status_code == 409


# --- 3. Reason required -------------------------------------------------------


def test_reopening_needs_a_reason(api, session, beds):
    week = settled_week(api, session, beds)
    response = api.post(f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": ""})
    assert response.status_code == 422

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.SETTLED


def test_a_whitespace_only_reason_is_refused_by_the_routine(api, session, beds):
    """pydantic's min_length=1 lets whitespace through; the routine does not."""
    week = settled_week(api, session, beds)
    response = api.post(f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "   "})
    assert response.status_code == 422

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.SETTLED


def test_a_blank_reason_is_refused_directly_by_the_routine(session, beds, api):
    week = settled_week(api, session, beds)
    session.expire_all()
    week = session.get(Week, week.id)
    authorisation = Authorisation(party=PARENT_PARTY, at=week.created_at)
    with pytest.raises(settlement.ReopenNeedsAReason):
        settlement.reopen(session, week, authorisation, reason="   ")


def test_a_reopen_states_its_reason_at_the_database_layer(session, beds, api):
    """A CHECK constraint refuses a blank reason even via raw SQL."""
    week = settled_week(api, session, beds)
    session.expire_all()
    week = session.get(Week, week.id)

    with pytest.raises((IntegrityError, OperationalError)):
        session.execute(
            text(
                "INSERT INTO week_reopenings (week_id, reopened_by, reopened_at, reason,"
                " previous_status, previous_base_pence, previous_chore_pay_pence,"
                " previous_bonus_pence, previous_reward_pence, previous_total_pence,"
                " previous_closed_at, was_paid, reversed_deposit_pence)"
                " VALUES (:week_id, 'parent', CURRENT_TIMESTAMP, '',"
                " 'settled', 100, 350, 0, 0, 450, CURRENT_TIMESTAMP, 0, 0)"
            ),
            {"week_id": week.id},
        )
    session.rollback()


# --- 4. Authorisation: PIN, per source, and reads stay open ------------------


def test_reopening_needs_the_pin(api, session, beds):
    week = settled_week(api, session, beds)
    response = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": WRONG, "reason": "Wrong figure"}
    )
    assert response.status_code == 401

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.SETTLED
    assert session.query(WeekReopening).count() == 0


def test_a_wrong_pin_to_reopen_counts_toward_the_lockout(api, session, beds):
    week = settled_week(api, session, beds)
    # The default limit is 5 consecutive failures before a cooling-off.
    for _ in range(5):
        response = api.post(
            f"/api/weeks/{week.id}/reopen", json={"pin": WRONG, "reason": "x"}
        )
        assert response.status_code == 401

    locked = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": WRONG, "reason": "x"}
    )
    assert locked.status_code == 429

    # And now even the correct PIN is refused until the cooling-off passes.
    correct = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Wrong figure"}
    )
    assert correct.status_code == 429


def test_reading_a_settled_week_is_not_an_authorisation_attempt(api, session, beds):
    """Reads never touch the attempt limiter — only a submitted PIN can."""
    week = settled_week(api, session, beds)
    for _ in range(10):
        assert api.get(f"/api/weeks/{week.id}").status_code == 200

    # Ten reads later, a correct PIN still works first time.
    response = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Wrong figure"}
    )
    assert response.status_code == 200


# --- 5. Only a closed week can be reopened -----------------------------------


def test_an_open_week_cannot_be_reopened(api, session, beds):
    week = _week_with_instances(session, beds, FIRST_SUNDAY, FIRST_SATURDAY, confirmed=0)
    response = api.post(
        f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Anything"}
    )
    assert response.status_code == 409


# --- 6. Re-settling is the ordinary path, no shortcuts -----------------------


def test_resettling_still_checks_the_agreed_figure_against_the_live_proposal(
    api, session, beds
):
    week = settled_week(api, session, beds)
    api.post(f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Second thoughts"})

    stale_figure = 450  # read before something else moved

    # Something changes between reading the proposal and agreeing it: a
    # confirmed instance is put right, exactly as in the card's own test.
    instance = (
        session.query(ChoreInstance)
        .filter(ChoreInstance.week_id == week.id)
        .order_by(ChoreInstance.due_date)
        .first()
    )
    session.expire_all()
    week_row = session.get(Week, week.id)
    instance = session.get(ChoreInstance, instance.id)
    instance.state = InstanceState.MISSED
    instance.confirmed_at = None
    instance.missed_at = week_row.created_at
    instance.miss_origin = MissOrigin.PARENT_MARKED
    instance.authorised_by = "parent"
    session.commit()

    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": stale_figure}
    )
    assert response.status_code == 409


def test_resettling_may_void_instead_and_void_still_refuses_an_assignment(api, session, beds):
    week = settled_week(api, session, beds)
    api.post(f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Second thoughts"})

    response = api.post(
        f"/api/weeks/{week.id}/void",
        json={
            "pin": PIN,
            "reason": "Grounded",
            "override": {"recoveries": []},
        },
    )
    assert response.status_code == 422  # a void takes no assignment, exactly as ever

    ordinary_void = api.post(
        f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": "Grounded"}
    )
    assert ordinary_void.status_code == 200
    assert ordinary_void.json()["status"] == "voided"


def test_a_resettled_weeks_lines_are_the_new_round_not_both(api, session, beds):
    week = settled_week(api, session, beds)
    session.expire_all()
    first_round_lines = len(session.get(Week, week.id).settlement_lines)
    assert first_round_lines > 0

    api.post(f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Redo it"})

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    resettled = api.post(
        f"/api/weeks/{week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": proposal["total_pence"]},
    ).json()

    # The API view shows only the current round...
    assert sum(line["amount_pence"] for line in resettled["lines"]) + resettled[
        "base_pence"
    ] == resettled["total_pence"]

    # ...but nothing was deleted: both rounds' lines are still in the table.
    session.expire_all()
    stored = session.get(Week, week.id)
    assert len(stored.settlement_lines) == first_round_lines * 2


# --- The weeks trigger: the single controlled exception, and nothing wider --


def test_a_settled_weeks_figures_still_cannot_be_edited_directly(api, session, beds):
    """The ordinary immutability guard is untouched by the new exception."""
    week = settled_week(api, session, beds)
    with pytest.raises((IntegrityError, OperationalError), match="closed forever"):
        session.execute(
            text("UPDATE weeks SET settled_total_pence = 9999 WHERE id = :id"),
            {"id": week.id},
        )
    session.rollback()


def test_flipping_status_alone_without_clearing_figures_still_aborts(api, session, beds):
    """A hand-typed update that reopens the status but leaves the old figures
    behind is not what the exception describes, and is still refused."""
    week = settled_week(api, session, beds)
    with pytest.raises((IntegrityError, OperationalError), match="closed forever"):
        session.execute(
            text("UPDATE weeks SET status = 'open' WHERE id = :id"), {"id": week.id}
        )
    session.rollback()
    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.SETTLED


def test_a_reopening_row_cannot_be_edited_or_deleted(api, session, beds):
    week = settled_week(api, session, beds)
    api.post(f"/api/weeks/{week.id}/reopen", json={"pin": PIN, "reason": "Second thoughts"})
    (reopening,) = session.query(WeekReopening).all()

    with pytest.raises((IntegrityError, OperationalError), match="not"):
        session.execute(
            text("UPDATE week_reopenings SET reason = 'edited' WHERE id = :id"),
            {"id": reopening.id},
        )
    session.rollback()

    with pytest.raises((IntegrityError, OperationalError), match="not"):
        session.execute(
            text("DELETE FROM week_reopenings WHERE id = :id"), {"id": reopening.id}
        )
    session.rollback()
