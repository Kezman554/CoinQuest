"""The monthly savings match: the ladder, the dipped-to low a withdrawal
forces, and a settled month's figures surviving a later change to the scheme.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models import SavingsMonthMatch
from app.models.base import utcnow
from app.services import savings, savings_match, scheme_settings
from app.services.authorisation import Authorisation
from app.services.savings_match import (
    MonthAlreadySettled,
    MonthNotOver,
    NoSavingsYet,
    ProposalChanged,
)

PIN = "0000"
WRONG = "9999"


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
    return savings.record_withdrawal(
        session, amount_pence=amount_pence, occurred_on=on, reason=reason
    )


def settle(session, tz):
    """Propose the next month and settle it on exactly what it proposes."""
    proposal = savings_match.propose(session, tz)
    authorisation = Authorisation(party="parent", at=utcnow())
    row = savings_match.settle(
        session, proposal, authorisation, agreed_match_pence=proposal.match_pence
    )
    session.commit()
    return row, proposal


# --- Reading a proposal: refuses what it must, and is otherwise inert ------


def test_no_savings_yet_refuses_a_proposal(session, tz):
    with pytest.raises(NoSavingsYet):
        savings_match.propose(session, tz)


def test_the_current_month_can_be_previewed_but_not_settled(session, tz):
    """propose() computes a live figure mid-month — Oliver's page and the
    parent panel both read it that way — but settle() refuses to close on
    one that has not finished yet."""
    from app.services.calendar import today

    opening_balance(session, on=today(tz).replace(day=1))
    session.commit()

    proposal = savings_match.propose(session, tz)
    assert proposal.month_has_ended is False

    authorisation = Authorisation(party="parent", at=utcnow())
    with pytest.raises(MonthNotOver):
        savings_match.settle(
            session, proposal, authorisation, agreed_match_pence=proposal.match_pence
        )
    assert session.query(SavingsMonthMatch).count() == 0


def test_a_finished_months_proposal_says_so(session, tz):
    opening_balance(session, on=date(2026, 1, 10))
    session.commit()

    proposal = savings_match.propose(session, tz)
    assert proposal.month_has_ended is True


def test_a_proposal_writes_nothing_however_often_it_is_read(session, tz):
    opening_balance(session, on=date(2026, 1, 10))
    session.commit()

    first = savings_match.propose(session, tz)
    second = savings_match.propose(session, tz)
    third = savings_match.propose(session, tz)

    assert first == second == third
    assert session.query(SavingsMonthMatch).count() == 0


# --- The ladder --------------------------------------------------------


def test_the_first_partial_month_counts_as_clean_and_earns_the_start_rate(session, tz):
    # Opened on the 10th of January: a partial month, but no withdrawal in it.
    opening_balance(session, amount_pence=1000, on=date(2026, 1, 10))
    session.commit()

    proposal = savings_match.propose(session, tz)
    assert proposal.period_start == date(2026, 1, 1)
    assert proposal.balance_low_pence == 1000  # the opening balance itself
    assert proposal.had_withdrawal is False
    assert proposal.rate_percent == 5
    assert proposal.match_pence == 50  # 5% of £10


def test_the_rate_climbs_a_point_a_clean_month_up_to_the_ceiling(session, tz):
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    # Six clean months: 5, 6, 7, 8, 9, 10 — the ceiling reached on the sixth.
    row = None
    for month_number, expected_rate in enumerate((5, 6, 7, 8, 9, 10), start=1):
        row, proposal = settle(session, tz)
        assert proposal.rate_percent == expected_rate
        assert proposal.clean_months_in_a_row == month_number
        assert row.rate_percent == expected_rate

    # A seventh clean month holds at the ceiling rather than climbing past it
    # — but the true streak keeps counting past where the rate stops.
    row, proposal = settle(session, tz)
    assert proposal.rate_percent == 10
    assert proposal.clean_months_in_a_row == 7


def test_a_withdrawal_resets_that_same_months_rate_to_the_start(session, tz):
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    # Three clean months first: rate reaches 7%.
    row = None
    for _ in range(3):
        row, _ = settle(session, tz)
    assert row.rate_percent == 7

    # Fourth month: a withdrawal happens in it. That month's own rate resets.
    withdraw(session, amount_pence=20_00, on=date(2026, 4, 15))
    session.commit()
    row, proposal = settle(session, tz)
    assert proposal.had_withdrawal is True
    assert row.rate_percent == 5
    assert proposal.clean_months_in_a_row == 0

    # Fifth month, clean again: climbs from the reset rate, not from 7%, and
    # the streak starts over at one rather than resuming from three.
    row, proposal = settle(session, tz)
    assert row.rate_percent == 6
    assert proposal.clean_months_in_a_row == 1


def test_a_reversal_is_not_a_withdrawal_and_does_not_reset_the_ladder(session, tz):
    """A reopened week's reversal lowers the balance but was not the child's
    own choice — it must not trip the same reset a withdrawal does."""
    from app.models.enums import SavingsType
    from app.models.ledgers import SavingsEntry

    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()
    row, _ = settle(session, tz)
    assert row.rate_percent == 5

    # A reversal in the second month — recorded directly, the way
    # settlement.reopen appends one, rather than through record_withdrawal.
    session.add(
        SavingsEntry(
            entry_type=SavingsType.REVERSAL,
            amount_pence=-10_00,
            balance_after_pence=savings.current_balance(session) - 10_00,
            occurred_on=date(2026, 2, 12),
            reason="Reversed: a week reopened",
        )
    )
    session.commit()

    row, proposal = settle(session, tz)
    assert proposal.had_withdrawal is False
    assert row.rate_percent == 6  # continued climbing, not reset to 5


# --- The dipped-to low ------------------------------------------------------


def test_a_withdrawal_months_match_pays_on_the_balance_after_the_withdrawal(session, tz):
    """A withdrawal month must not be matched on the whole month's low —
    it is matched on where the balance settled after the withdrawal."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()
    settle(session, tz)  # January closes clean, at 5%, balance now £105

    # February: a deposit lifts the balance well above where it started,
    # then a withdrawal drops it to £20.
    deposit(session, amount_pence=50_00, on=date(2026, 2, 3))
    withdraw(session, amount_pence=135_00, on=date(2026, 2, 10))
    session.commit()

    proposal = savings_match.propose(session, tz)
    assert proposal.had_withdrawal is True
    assert proposal.balance_low_pence == 20_00  # the dipped-to low
    assert proposal.rate_percent == 5  # reset, not the 6% a clean month would earn
    assert proposal.match_pence == 100  # 5% of £20


def test_multiple_withdrawals_in_one_month_use_the_lowest_point_after_the_first(session, tz):
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    withdraw(session, amount_pence=10_00, on=date(2026, 1, 12))  # -> £90
    deposit(session, amount_pence=50_00, on=date(2026, 1, 15))  # -> £140
    withdraw(session, amount_pence=100_00, on=date(2026, 1, 20))  # -> £40

    proposal = savings_match.propose(session, tz)
    assert proposal.balance_low_pence == 40_00


# --- The cap: a rate ceiling, not a stop ------------------------------------


def test_match_pence_matches_the_worked_example(session, tz):
    """A £250 balance at 10%, capped at £100, pays £10 — not £25."""
    assert (
        savings_match.match_pence(low_pence=250_00, rate_percent=10, cap_pence=100_00) == 1000
    )


def test_the_cap_keeps_paying_the_same_match_as_the_balance_climbs_past_it(session, tz):
    opening_balance(session, amount_pence=250_00, on=date(2026, 1, 5))
    session.commit()

    # Climb to the 10% ceiling first (six clean months, matches added each
    # one meaning the balance is already well past the £100 cap by now).
    row = None
    for _ in range(6):
        row, _ = settle(session, tz)
    assert row.rate_percent == 10

    row, proposal = settle(session, tz)  # seventh clean month, held at 10%
    assert proposal.rate_percent == 10
    assert proposal.balance_low_pence > proposal.cap_pence
    assert proposal.match_pence == 1000  # 10% of the £100 cap, however high the balance is


def test_a_balance_under_the_cap_is_matched_on_itself(session, tz):
    opening_balance(session, amount_pence=40_00, on=date(2026, 1, 5))
    session.commit()

    proposal = savings_match.propose(session, tz)
    assert proposal.rate_percent == 5
    assert proposal.match_pence == 200  # 5% of £40, under the £100 cap


# --- Settling: a closed event, PIN-guarded, refuses a second attempt -------


def test_settling_through_the_api_writes_a_closed_month(api, session):
    opening_balance(session, on=date(2026, 1, 5))
    session.commit()

    proposal = api.get("/api/savings/match/proposal").json()
    assert proposal["match_pence"] == 50

    response = api.post(
        "/api/savings/match/settle",
        json={"pin": PIN, "agreed_match_pence": 50},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["match_pence"] == 50
    assert body["rate_percent"] == 5
    assert body["settled_by"] == "parent"

    listed = api.get("/api/savings/match").json()
    assert len(listed) == 1
    assert listed[0]["period_start"] == "2026-01-01"


def test_settling_without_the_pin_is_refused(api, session):
    opening_balance(session, on=date(2026, 1, 5))
    session.commit()

    response = api.post(
        "/api/savings/match/settle",
        json={"pin": WRONG, "agreed_match_pence": 50},
    )
    assert response.status_code == 401
    assert api.get("/api/savings/match").json() == []


def test_the_match_lands_on_the_savings_ledger(api, session):
    opening_balance(session, amount_pence=1000, on=date(2026, 1, 5))
    session.commit()

    api.post("/api/savings/match/settle", json={"pin": PIN, "agreed_match_pence": 50})

    savings_view = api.get("/api/savings").json()
    assert savings_view["balance_pence"] == 1050
    match_entries = [e for e in savings_view["entries"] if e["entry_type"] == "match"]
    assert len(match_entries) == 1
    assert match_entries[0]["amount_pence"] == 50


def test_a_month_cannot_be_settled_twice(session, tz):
    opening_balance(session, on=date(2026, 1, 5))
    session.commit()

    proposal = savings_match.propose(session, tz)
    authorisation = Authorisation(party="parent", at=utcnow())
    savings_match.settle(
        session, proposal, authorisation, agreed_match_pence=proposal.match_pence
    )
    session.commit()

    with pytest.raises(MonthAlreadySettled):
        savings_match.settle(
            session, proposal, authorisation, agreed_match_pence=proposal.match_pence
        )


def test_settling_on_a_stale_figure_is_refused(session, tz):
    opening_balance(session, amount_pence=1000, on=date(2026, 1, 5))
    session.commit()

    proposal = savings_match.propose(session, tz)
    authorisation = Authorisation(party="parent", at=utcnow())
    with pytest.raises(ProposalChanged):
        savings_match.settle(
            session, proposal, authorisation, agreed_match_pence=proposal.match_pence + 1
        )
    assert session.query(SavingsMonthMatch).count() == 0


def test_reopening_a_settled_month_does_not_exist(api, session):
    """Deliberately out of scope: there is no endpoint for it at all.

    405, not 404: an unmatched POST under this API falls through to the
    frontend's SPA mount, which refuses anything but GET/HEAD — the same
    thing that happens to any other made-up POST path in this app, and not
    specific to this route. What matters here is that nothing answers it.
    """
    opening_balance(session, on=date(2026, 1, 5))
    session.commit()
    api.post("/api/savings/match/settle", json={"pin": PIN, "agreed_match_pence": 50})

    assert api.post("/api/savings/match/reopen", json={"pin": PIN}).status_code == 405


# --- A settled month is a closed event --------------------------------------


def test_a_settled_months_figures_survive_a_change_to_the_ceiling(api, session):
    opening_balance(session, amount_pence=250_00, on=date(2026, 1, 5))
    session.commit()

    response = api.post(
        "/api/savings/match/settle", json={"pin": PIN, "agreed_match_pence": 500}
    )
    assert response.status_code == 200
    settled = response.json()
    assert settled["rate_percent"] == 5
    assert settled["cap_pence"] == 10000
    assert settled["match_pence"] == 500  # 5% of the £100 cap, not of the £250 balance

    # A parent raises the cap and the ceiling rate at the next review.
    row = scheme_settings.get_row(session)
    row.savings_match_cap_pence = 100_000_00
    row.savings_match_ceiling_rate_percent = 50
    session.commit()

    # The already-settled month reads exactly as it did before the change.
    unchanged = api.get("/api/savings/match").json()[0]
    assert unchanged["rate_percent"] == 5
    assert unchanged["cap_pence"] == 10000
    assert unchanged["match_pence"] == 500
