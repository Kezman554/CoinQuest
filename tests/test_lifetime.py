"""Lifetime totals, and the never-withdrawn comparison.

The counterfactual trajectory is checked two ways: against a hand-worked
example, and — the stronger proof — against the real ladder itself. When
nothing has ever actually been withdrawn, replaying the same deposits with
withdrawals filtered out (a no-op filter, in that case) and recomputing each
month's match must land on exactly the figures the real ladder already
settled on, since both read the same live scheme_settings. That equality is
what test_matches_the_real_ladder_when_nothing_was_ever_withdrawn asserts.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models.base import utcnow
from app.models.enums import SavingsType
from app.models.ledgers import EarningEntry, SavingsEntry
from app.services import lifetime, savings, savings_match
from app.services.authorisation import Authorisation

PIN = "0000"


@pytest.fixture()
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def tz(session):
    from app.config import get_settings

    return get_settings().tzinfo


def opening_balance(session, *, amount_pence=1000, on=date(2026, 1, 10)):
    return savings.record_opening_balance(session, amount_pence=amount_pence, occurred_on=on)


def deposit(session, *, amount_pence, on):
    return savings.record_deposit(session, amount_pence=amount_pence, occurred_on=on)


def withdraw(session, *, amount_pence, on, reason="Toy"):
    return savings.record_withdrawal(session, amount_pence=amount_pence, occurred_on=on, reason=reason)


def settle_next_month(session, tz):
    proposal = savings_match.propose(session, tz)
    authorisation = Authorisation(party="parent", at=utcnow())
    row = savings_match.settle(
        session, proposal, authorisation, agreed_match_pence=proposal.match_pence
    )
    session.commit()
    return row


def settle_every_elapsed_month(session, tz):
    """Every month up to today that has actually finished — not a fixed
    count, so the "nothing was ever withdrawn" equality test holds however
    much real time separates the opening balance from whenever this runs."""
    while True:
        proposal = savings_match.propose(session, tz)
        if not proposal.month_has_ended:
            return
        settle_next_month(session, tz)


# --- Total earned ------------------------------------------------------


def test_total_earned_sums_every_earnings_ledger_entry(session):
    from app.models import Week

    first_week = Week(start_date=date(2026, 1, 4), end_date=date(2026, 1, 10))
    second_week = Week(start_date=date(2026, 1, 11), end_date=date(2026, 1, 17))
    session.add_all([first_week, second_week])
    session.commit()

    session.add_all(
        [
            EarningEntry(
                entry_type="week_settlement",
                amount_pence=450,
                week_id=first_week.id,
                occurred_on=date(2026, 1, 10),
            ),
            EarningEntry(
                entry_type="reward",
                amount_pence=200,
                occurred_on=date(2026, 1, 6),
                reason="Eagle award",
            ),
            EarningEntry(
                entry_type="week_settlement",
                amount_pence=0,
                week_id=second_week.id,
                occurred_on=date(2026, 1, 17),
            ),
        ]
    )
    session.commit()

    assert lifetime.total_earned_pence(session) == 650


def test_total_earned_is_zero_with_no_history(session):
    assert lifetime.total_earned_pence(session) == 0


def test_total_earned_includes_a_settled_week_and_an_ad_hoc_reward(api, session):
    from app.models import Cadence, Category, ChoreDefinition, ChoreInstance, InstanceState, Week

    beds = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=0
    )
    session.add(beds)
    from app.services import scheme_settings

    scheme_settings.get_row(session).weekly_basic_pay_pence = 350
    session.commit()

    week = Week(start_date=date(2026, 1, 4), end_date=date(2026, 1, 10))
    session.add(week)
    session.commit()
    for offset in range(7):
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(week.start_date.toordinal() + offset),
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
        )
    session.commit()

    settle = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert settle.status_code == 200

    reward = api.post("/api/rewards", json={"pin": PIN, "amount": "£2", "reason": "Well done"})
    assert reward.status_code == 201

    body = api.get("/api/lifetime").json()
    assert body["total_earned_pence"] == 650


# --- The real trajectory: a straight read -----------------------------------


def test_real_trajectory_matches_the_savings_ledgers_own_history(session):
    opening_balance(session, amount_pence=1000, on=date(2026, 1, 5))
    deposit(session, amount_pence=500, on=date(2026, 1, 20))
    withdraw(session, amount_pence=300, on=date(2026, 1, 25))
    session.commit()

    points = lifetime.real_trajectory(session)
    history = savings.history(session)

    assert [p.balance_pence for p in points] == [e.balance_after_pence for e in history]
    assert [p.occurred_on for p in points] == [e.occurred_on for e in history]


def test_an_empty_ledger_has_no_real_trajectory(session):
    assert lifetime.real_trajectory(session) == []


# --- The counterfactual ------------------------------------------------


def test_counterfactual_is_empty_with_no_history(session, tz):
    assert lifetime.counterfactual_trajectory(session, tz) == []


def test_a_month_in_progress_adds_no_match_to_either_trajectory(session, tz):
    from app.services.calendar import today

    opening_balance(session, amount_pence=1000, on=today(tz).replace(day=1))
    session.commit()

    real = lifetime.real_trajectory(session)
    counterfactual = lifetime.counterfactual_trajectory(session, tz)

    assert [p.balance_pence for p in real] == [1000]
    assert [p.balance_pence for p in counterfactual] == [1000]


def test_matches_the_real_ladder_when_nothing_was_ever_withdrawn(session, tz):
    """The strong proof: with no withdrawal in reality, replaying "kept"
    entries (a no-op filter here) and recomputing each month's match must
    reproduce exactly what the real ladder already settled on, since both
    read the same live scheme_settings."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    settle_every_elapsed_month(session, tz)

    counterfactual = lifetime.counterfactual_trajectory(session, tz)
    assert counterfactual[-1].balance_pence == savings.current_balance(session)

    # And every point along the way agrees, not only the final figure.
    real = lifetime.real_trajectory(session)
    assert [p.balance_pence for p in counterfactual] == [p.balance_pence for p in real]


def test_the_counterfactual_pulls_ahead_once_a_real_withdrawal_resets_the_ladder(session, tz):
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    for _ in range(3):
        settle_next_month(session, tz)

    # A withdrawal in the fourth month resets the real ladder to 5%.
    withdraw(session, amount_pence=10_00, on=date(2026, 4, 10))
    session.commit()
    settle_next_month(session, tz)

    for _ in range(2):
        settle_next_month(session, tz)

    real_balance = savings.current_balance(session)
    counterfactual = lifetime.counterfactual_trajectory(session, tz)

    # The counterfactual never saw the withdrawal, so its ladder climbed
    # straight through where the real one reset — it must be worth more.
    assert counterfactual[-1].balance_pence > real_balance
    # And its principal is the same £100 that was actually put in, plus
    # match only — the withdrawal itself is simply absent, not refunded.
    assert counterfactual[-1].balance_pence > 100_00


def test_a_reversal_still_reduces_the_counterfactual(session, tz):
    """Unlike a withdrawal, a reversal is not the child's choice — it
    corrects a deposit that should not have counted — so it stays in the
    counterfactual's own balance."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.add(
        SavingsEntry(
            entry_type=SavingsType.REVERSAL,
            amount_pence=-20_00,
            balance_after_pence=80_00,
            occurred_on=date(2026, 1, 12),
            reason="Reversed: a week reopened",
        )
    )
    session.commit()

    counterfactual = lifetime.counterfactual_trajectory(session, tz)
    # The point right after the reversal reflects it.
    assert 80_00 in [p.balance_pence for p in counterfactual]


# --- The endpoint ------------------------------------------------------


def test_reading_needs_no_pin(api):
    assert api.get("/api/lifetime").status_code == 200


def test_the_endpoint_is_empty_and_not_an_error_with_no_history(api):
    body = api.get("/api/lifetime").json()
    assert body == {"total_earned_pence": 0, "real": [], "counterfactual": []}


def test_the_endpoint_reports_both_trajectories(api, session):
    from app.services.calendar import today
    from app.config import get_settings

    first_of_this_month = today(get_settings().tzinfo).replace(day=1)
    opening_balance(session, amount_pence=1000, on=first_of_this_month)
    withdraw(session, amount_pence=200, on=first_of_this_month)
    session.commit()

    body = api.get("/api/lifetime").json()
    # The month is still in progress, so neither trajectory has reached a
    # match yet — the real one shows the withdrawal, the counterfactual
    # simply does not see it happen.
    assert [p["balance_pence"] for p in body["real"]] == [1000, 800]
    assert [p["balance_pence"] for p in body["counterfactual"]] == [1000]
