"""A standalone savings deposit: Oliver's pending proposal and a parent's
direct one, and proof neither disturbs the monthly match's ladder or streak.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models import DepositRequestState, PendingSavingsDeposit, SavingsEntry, SavingsType
from app.services import savings, savings_match

PIN = "0000"
WRONG = "9999"
CHILD = "Test Child"
PARENT = "Test Parent"


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


def opened(session, *, amount_pence=1000, on=date(2026, 1, 5)):
    """Some money already in the account, so a submitted deposit is not the
    ledger's first entry — irrelevant to this feature, but keeps every test
    from also having to think about the opening-balance-must-be-first rule."""
    savings.record_opening_balance(session, amount_pence=amount_pence, occurred_on=on)
    session.commit()


# --- Depositors, the fixed list ---------------------------------------------


def test_the_depositor_list_names_the_child_and_the_parents(api):
    body = api.get("/api/savings/deposits/depositors").json()
    assert body["child_name"] == CHILD
    assert body["parent_names"] == [PARENT]


# --- Oliver submits: pending, and inert on the balance ----------------------


def test_a_child_submitted_deposit_is_pending_and_does_not_move_the_balance(api, session):
    opened(session)
    response = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "pending"
    assert body["amount_pence"] == 500
    assert body["note"] == "Birthday money"
    assert body["posted_by"] == CHILD
    assert body["decided_at"] is None

    # The balance has not moved, and no ledger entry exists for it yet.
    assert api.get("/api/savings").json()["balance_pence"] == 1000
    assert session.query(SavingsEntry).count() == 1  # only the opening balance


def test_submitting_needs_no_pin(api, session):
    opened(session)
    response = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    )
    assert response.status_code == 201


def test_a_parent_cannot_submit_through_the_child_s_door(api, session):
    """The waiting door is the child's alone — a parent posting as itself
    here would be a way around the PIN, so it is refused."""
    opened(session)
    response = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Pocket money", "posted_by": PARENT},
    )
    assert response.status_code == 409
    assert session.query(PendingSavingsDeposit).count() == 0


def test_an_unrecognised_name_is_refused(api, session):
    opened(session)
    response = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "?", "posted_by": "Someone Else"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"amount_pence": 0, "note": "x", "posted_by": CHILD},
        {"amount_pence": -100, "note": "x", "posted_by": CHILD},
        {"amount_pence": 100, "note": "", "posted_by": CHILD},
        {"amount_pence": 100, "note": "   ", "posted_by": CHILD},
    ],
)
def test_a_deposit_needs_a_positive_amount_and_a_real_note(api, session, body):
    opened(session)
    response = api.post("/api/savings/deposits", json=body)
    assert response.status_code in (409, 422)
    assert session.query(PendingSavingsDeposit).count() == 0


def test_pending_deposits_are_listed_oldest_first(api, session):
    opened(session)
    first = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 200, "note": "First", "posted_by": CHILD},
    ).json()
    second = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 300, "note": "Second", "posted_by": CHILD},
    ).json()

    listed = api.get("/api/savings/deposits/pending").json()
    assert [item["id"] for item in listed] == [first["id"], second["id"]]


# --- A parent confirms or rejects -------------------------------------------


def test_a_parent_confirms_a_pending_deposit_and_it_lands_in_the_ledger(api, session):
    opened(session)
    request = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    ).json()

    response = api.post(
        f"/api/savings/deposits/{request['id']}/confirm", json={"pin": PIN}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "confirmed"
    assert body["decided_by"] == "parent"
    assert body["decided_at"] is not None

    assert api.get("/api/savings").json()["balance_pence"] == 1500
    entry = session.query(SavingsEntry).order_by(SavingsEntry.id.desc()).first()
    assert entry.entry_type is SavingsType.DEPOSIT
    assert entry.amount_pence == 500
    assert entry.posted_by == CHILD
    assert entry.reason == "Birthday money"

    # No longer in the pending queue.
    assert api.get("/api/savings/deposits/pending").json() == []


def test_confirming_needs_the_pin(api, session):
    opened(session)
    request = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    ).json()

    response = api.post(
        f"/api/savings/deposits/{request['id']}/confirm", json={"pin": WRONG}
    )
    assert response.status_code == 401
    assert api.get("/api/savings").json()["balance_pence"] == 1000
    assert session.get(PendingSavingsDeposit, request["id"]).state is DepositRequestState.PENDING


def test_a_parent_rejects_a_pending_deposit_and_the_ledger_never_hears_of_it(api, session):
    opened(session)
    request = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Not real", "posted_by": CHILD},
    ).json()

    response = api.post(
        f"/api/savings/deposits/{request['id']}/reject", json={"pin": PIN}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "rejected"

    assert api.get("/api/savings").json()["balance_pence"] == 1000
    assert session.query(SavingsEntry).count() == 1  # only the opening balance


def test_a_decided_deposit_cannot_be_decided_again(api, session):
    opened(session)
    request = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    ).json()
    api.post(f"/api/savings/deposits/{request['id']}/confirm", json={"pin": PIN})

    again = api.post(f"/api/savings/deposits/{request['id']}/confirm", json={"pin": PIN})
    assert again.status_code == 409

    rejected_now = api.post(f"/api/savings/deposits/{request['id']}/reject", json={"pin": PIN})
    assert rejected_now.status_code == 409

    # The balance only ever moved once.
    assert api.get("/api/savings").json()["balance_pence"] == 1500


def test_confirming_an_unknown_request_is_a_404(api, session):
    response = api.post("/api/savings/deposits/999/confirm", json={"pin": PIN})
    assert response.status_code == 404


# --- A parent posts directly: immediate, no pending step --------------------


def test_a_parent_posted_deposit_lands_immediately(api, session):
    opened(session)
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": PIN, "amount_pence": 700, "note": "Gift from Grandma", "posted_by": PARENT},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["entry_type"] == "deposit"
    assert body["amount_pence"] == 700
    assert body["balance_after_pence"] == 1700
    assert body["posted_by"] == PARENT

    assert api.get("/api/savings").json()["balance_pence"] == 1700
    # No pending row was ever created for it.
    assert session.query(PendingSavingsDeposit).count() == 0


def test_a_parent_posted_deposit_needs_the_pin(api, session):
    opened(session)
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": WRONG, "amount_pence": 700, "note": "Gift", "posted_by": PARENT},
    )
    assert response.status_code == 401
    assert api.get("/api/savings").json()["balance_pence"] == 1000


def test_a_parent_cannot_post_as_the_child(api, session):
    opened(session)
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": PIN, "amount_pence": 700, "note": "Gift", "posted_by": CHILD},
    )
    assert response.status_code == 409
    assert api.get("/api/savings").json()["balance_pence"] == 1000


def test_the_opening_balance_can_be_entered_this_way_too(api, session):
    """The intended go-live route: a parent posting a deposit with a note
    like "opening balance" — a plain DEPOSIT, not the dedicated
    opening-balance endpoint, and it works identically as the ledger's
    first entry."""
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": PIN, "amount_pence": 1000, "note": "Opening balance", "posted_by": PARENT},
    )
    assert response.status_code == 201
    assert response.json()["balance_after_pence"] == 1000
    assert api.get("/api/savings").json()["balance_pence"] == 1000


# --- Interplay with the monthly match: neither the streak nor the ladder ----
# --- moves for a deposit — only a withdrawal does that. ---------------------


def test_a_confirmed_deposit_does_not_reset_the_ladder_or_the_streak(api, session, tz):
    from app.services.calendar import month_containing

    month_start = date(2026, 3, 1)
    opened(session, amount_pence=1000, on=month_start)

    request = api.post(
        "/api/savings/deposits",
        json={
            "amount_pence": 500,
            "note": "Birthday money",
            "posted_by": CHILD,
            "occurred_on": date(2026, 3, 10).isoformat(),
        },
    ).json()
    api.post(f"/api/savings/deposits/{request['id']}/confirm", json={"pin": PIN})

    end = month_containing(month_start, tz).end
    assert date(2026, 3, 10) <= end  # sanity: the deposit really lands in March

    proposal = savings_match.propose(session, tz)
    assert proposal.had_withdrawal is False
    # The low is the pre-deposit opening balance, never the (higher) figure
    # after a deposit — a deposit can only ever raise the balance, so it can
    # never itself become a new low.
    assert proposal.balance_low_pence == 1000
    assert proposal.clean_months_in_a_row == 1
    assert proposal.rate_percent == 5  # the seeded start rate, undisturbed


def test_a_parent_posted_deposit_also_leaves_the_ladder_undisturbed(api, session, tz):
    opened(session, amount_pence=1000, on=date(2026, 3, 1))
    api.post(
        "/api/savings/deposits/parent",
        json={
            "pin": PIN,
            "amount_pence": 500,
            "note": "Gift",
            "posted_by": PARENT,
            "occurred_on": date(2026, 3, 15).isoformat(),
        },
    )

    proposal = savings_match.propose(session, tz)
    assert proposal.had_withdrawal is False
    assert proposal.balance_low_pence == 1000
