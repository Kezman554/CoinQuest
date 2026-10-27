"""More than one parent: each PIN proves which parent is acting.

The configured parents (tests/conftest.py) are made up: "Test Parent" on 0000,
the bank holder, and "Test Second" on 1111. What a PIN proves is recorded by
name; what it allows is everything, except settling the savings match, which
only the bank holder can — they are the one who pays it into the bank.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.models import SavingsMonthMatch
from app.models.base import utcnow
from app.services import savings
from app.services.authorisation import PARENT, NotAuthorised, verify_pin

HOLDER, HOLDER_PIN = "Test Parent", "0000"
SECOND, SECOND_PIN = "Test Second", "1111"
WRONG = "9999"


@pytest.fixture()
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _a_month_to_settle(session):
    """An account opened on the first of last month: last month has ended,
    is unsettled, and pays a match."""
    from app.config import get_settings
    from app.services.calendar import today

    now = today(get_settings().tzinfo)
    first = date(now.year - (now.month == 1), (now.month - 2) % 12 + 1, 1)
    savings.record_opening_balance(session, amount_pence=2000, occurred_on=first)
    session.commit()


def _settle(api, pin, **extra):
    proposal = api.get("/api/savings/match/proposal").json()
    return api.post(
        "/api/savings/match/settle",
        json={"pin": pin, "agreed_match_pence": proposal["match_pence"], **extra},
    )


# --- Each PIN proves its own parent --------------------------------------------


def test_each_pin_proves_its_own_parent():
    holder = verify_pin(HOLDER_PIN)
    second = verify_pin(SECOND_PIN)
    assert (holder.party, holder.bank_holder) == (HOLDER, True)
    assert (second.party, second.bank_holder) == (SECOND, False)


def test_an_unknown_pin_is_refused():
    with pytest.raises(NotAuthorised):
        verify_pin(WRONG)


def test_an_unknown_pin_counts_towards_the_lockout(api, session):
    # Counted per source, shared by every parent: five wrong guesses lock the
    # source out, and then even a right PIN is turned away until it cools off.
    _a_month_to_settle(session)
    for _ in range(5):
        assert _settle(api, WRONG).status_code == 401
    assert _settle(api, HOLDER_PIN).status_code == 429


# --- Configuration is refused rather than guessed at ---------------------------


def _only(monkeypatch, **parents):
    """Exactly these PARENT_n_* variables, and no others."""
    import os

    for key in list(os.environ):
        if key.startswith("PARENT_") and key[7:8].isdigit():
            monkeypatch.delenv(key)
    for key, value in parents.items():
        monkeypatch.setenv(key, value)


def test_two_parents_with_the_same_pin_refuse_to_start(monkeypatch):
    _only(monkeypatch, PARENT_1_NAME="A", PARENT_1_PIN="2468", PARENT_2_NAME="B", PARENT_2_PIN="2468")
    with pytest.raises(ConfigError, match="share a PIN"):
        Settings()


@pytest.mark.parametrize("empty", ["PARENT_1_PIN", "PARENT_2_PIN", "PARENT_2_NAME"])
def test_an_empty_pin_or_name_refuses_to_start(monkeypatch, empty):
    _only(monkeypatch, PARENT_1_NAME="A", PARENT_1_PIN="2468", PARENT_2_NAME="B", PARENT_2_PIN="1357")
    monkeypatch.setenv(empty, "")
    with pytest.raises(ConfigError, match=empty):
        Settings()


def test_a_pair_left_entirely_empty_is_no_parent(monkeypatch):
    # How a compose file says there is no second parent: it passes the
    # variables through, empty.
    _only(monkeypatch, PARENT_1_NAME="A", PARENT_1_PIN="2468", PARENT_2_NAME="", PARENT_2_PIN="")
    monkeypatch.setenv("BANK_HOLDER", "1")
    assert [parent.name for parent in Settings().parents] == ["A"]


def test_no_parent_at_all_refuses_to_start(monkeypatch):
    _only(monkeypatch)
    with pytest.raises(ConfigError, match="No parent"):
        Settings()


def test_two_parents_with_the_same_name_refuse_to_start(monkeypatch):
    _only(monkeypatch, PARENT_1_NAME="A", PARENT_1_PIN="2468", PARENT_2_NAME="A", PARENT_2_PIN="1357")
    with pytest.raises(ConfigError, match="share a name"):
        Settings()


def test_a_name_too_long_to_record_refuses_to_start(monkeypatch):
    _only(monkeypatch, PARENT_1_NAME="A" * 61, PARENT_1_PIN="2468")
    monkeypatch.setenv("BANK_HOLDER", "1")
    with pytest.raises(ConfigError, match="longer than 60"):
        Settings()


@pytest.mark.parametrize("holder", ["", "3", "one"])
def test_the_bank_holder_must_be_a_configured_parent(monkeypatch, holder):
    monkeypatch.setenv("BANK_HOLDER", holder)
    with pytest.raises(ConfigError, match="BANK_HOLDER"):
        Settings()


@pytest.mark.parametrize("retired", ["PARENT_PIN", "PARENT_NAMES"])
def test_a_retired_variable_still_set_refuses_to_start(monkeypatch, retired):
    monkeypatch.setenv(retired, "0000")
    with pytest.raises(ConfigError, match=f"Remove {retired}"):
        Settings()


# --- The one restriction: the interest is the bank holder's to settle ------------


def test_the_second_parent_cannot_settle_the_interest(api, session):
    _a_month_to_settle(session)
    response = _settle(api, SECOND_PIN)
    assert response.status_code == 403
    assert response.json()["detail"] == (
        f"Only {HOLDER} can settle the interest, because it is paid into the bank."
    )
    assert session.query(SavingsMonthMatch).count() == 0


def test_that_refusal_is_not_a_failed_pin_attempt(api, session):
    # The PIN was right; the act was not theirs. However often it is tried, the
    # source is never locked out for it.
    _a_month_to_settle(session)
    for _ in range(6):
        assert _settle(api, SECOND_PIN).status_code == 403
    assert _settle(api, HOLDER_PIN).status_code == 200


def test_a_bank_balance_given_with_it_is_refused_with_it(api, session):
    _a_month_to_settle(session)
    response = _settle(api, SECOND_PIN, bank_balance_pence=2100)
    assert response.status_code == 403
    assert "reconciliation" not in response.json()


def test_the_bank_holder_settles_it_and_the_balance_is_checked(api, session):
    _a_month_to_settle(session)
    proposal = api.get("/api/savings/match/proposal").json()
    after = 2000 + proposal["match_pence"]
    response = _settle(api, HOLDER_PIN, bank_balance_pence=after)
    assert response.status_code == 200
    body = response.json()
    assert body["settled_by"] == HOLDER
    assert body["reconciliation"]["agrees"] is True
    assert body["reconciliation"]["recorded_balance_pence"] == after


def test_settling_without_a_bank_balance_checks_nothing(api, session):
    _a_month_to_settle(session)
    response = _settle(api, HOLDER_PIN)
    assert response.status_code == 200
    assert response.json()["reconciliation"] is None


# --- New rows carry the name; old rows keep "parent" -----------------------------


def test_a_parent_deposit_is_posted_by_whoever_the_pin_proves(api, session):
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": SECOND_PIN, "amount_pence": 500, "note": "Birthday money"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["posted_by"] == SECOND


def test_a_parent_deposit_naming_someone_else_is_refused(api, session):
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": SECOND_PIN, "amount_pence": 500, "note": "Gift", "posted_by": HOLDER},
    )
    assert response.status_code == 409
    assert savings.current_balance(session) == 0


def test_an_old_row_recorded_as_parent_still_reads(api, session):
    # Before parents had names, every authorisation was recorded as "parent".
    # Those rows are append-only and never rewritten; they read as they are,
    # and the parent view shows them as "a parent".
    _a_month_to_settle(session)
    entry = savings.record_match(session, amount_pence=100, occurred_on=date(2020, 1, 31))
    session.add(
        SavingsMonthMatch(
            period_start=date(2020, 1, 1),
            period_end=date(2020, 1, 31),
            balance_low_pence=2000,
            had_withdrawal=False,
            rate_percent=5,
            cap_pence=10000,
            match_pence=100,
            match_entry_id=entry.id,
            settled_by=PARENT,
            settled_at=utcnow(),
        )
    )
    session.commit()
    response = api.get("/api/savings/match")
    assert response.status_code == 200
    assert [row["settled_by"] for row in response.json()] == [PARENT]
