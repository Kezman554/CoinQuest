"""Payday, the savings ledger, and rewards a parent enters directly."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

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
    Week,
    WeekStatus,
)

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
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=350
    )
    session.add(definition)
    session.commit()
    return definition


def settled_week(api, session, beds, start=FIRST_SUNDAY, end=FIRST_SATURDAY) -> Week:
    """A perfect week, settled. Worth 100p base + 350p chore pay."""
    week = Week(start_date=start, end_date=end)
    session.add(week)
    session.commit()

    for offset in range(7):
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(start.toordinal() + offset),
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
        )
    session.commit()

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert proposal["total_pence"] == 450
    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert response.status_code == 200
    return week


# --- 1. Settling and paying are two acts ------------------------------------


def test_a_settled_week_reads_as_owed_until_it_is_paid(api, session, beds):
    week = settled_week(api, session, beds)

    (owed,) = api.get("/api/weeks/owed/outstanding").json()
    assert owed["week_id"] == week.id
    assert owed["owed_pence"] == 450
    assert owed["is_paid"] is False

    session.expire_all()
    assert session.get(Week, week.id).paid_at is None


def test_paying_is_separately_authorised(api, session, beds):
    week = settled_week(api, session, beds)

    response = api.post(
        "/api/weeks/payments",
        json={"pin": WRONG, "week_ids": [week.id], "deposited_pence": 0},
    )
    assert response.status_code == 401

    session.expire_all()
    assert session.get(Week, week.id).paid_at is None
    assert api.get("/api/weeks/owed/outstanding").json() != []


def test_a_paid_week_stops_reading_as_owed(api, session, beds):
    week = settled_week(api, session, beds)
    response = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 0, "occurred_on": PAYDAY.isoformat()},
    )
    assert response.status_code == 200
    assert api.get("/api/weeks/owed/outstanding").json() == []

    session.expire_all()
    assert session.get(Week, week.id).paid_at is not None


def test_an_unsettled_week_cannot_be_paid(api, session, beds):
    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()

    response = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 0},
    )
    assert response.status_code == 409
    assert "separate acts" in response.json()["detail"]


def test_a_week_cannot_be_paid_twice(api, session, beds):
    week = settled_week(api, session, beds)
    body = {"pin": PIN, "week_ids": [week.id], "deposited_pence": 0}
    assert api.post("/api/weeks/payments", json=body).status_code == 200
    again = api.post("/api/weeks/payments", json=body)
    assert again.status_code == 409
    assert "already paid" in again.json()["detail"]


# --- 2 and 3. One payment, several weeks, and the deposit -------------------


def test_two_settled_weeks_are_paid_in_one_action(api, session, beds):
    first = settled_week(api, session, beds)
    second = settled_week(api, session, beds, SECOND_SUNDAY, SECOND_SATURDAY)

    outstanding = api.get("/api/weeks/owed/outstanding").json()
    assert [owed["week_id"] for owed in outstanding] == [first.id, second.id]
    assert sum(owed["owed_pence"] for owed in outstanding) == 900

    response = api.post(
        "/api/weeks/payments",
        json={
            "pin": PIN,
            "week_ids": [first.id, second.id],
            "deposited_pence": 500,
            "occurred_on": PAYDAY.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["paid_pence"] == 900
    assert body["deposited_pence"] == 500
    assert body["kept_pence"] == 400
    assert body["savings_balance_pence"] == 500

    assert api.get("/api/weeks/owed/outstanding").json() == []


def test_the_deposits_land_on_the_savings_ledger(api, session, beds):
    first = settled_week(api, session, beds)
    second = settled_week(api, session, beds, SECOND_SUNDAY, SECOND_SATURDAY)

    api.post(
        "/api/weeks/payments",
        json={
            "pin": PIN,
            "week_ids": [first.id, second.id],
            "deposited_pence": 500,
            "occurred_on": PAYDAY.isoformat(),
        },
    )

    entries = session.query(SavingsEntry).order_by(SavingsEntry.id).all()
    assert len(entries) == 2

    # Apportioned in date order: the first week's 450p, then 50p of the second.
    assert [entry.amount_pence for entry in entries] == [450, 50]
    assert [entry.week_id for entry in entries] == [first.id, second.id]
    assert all(entry.entry_type is SavingsType.DEPOSIT for entry in entries)

    # Each row carries the balance after it, written once.
    assert [entry.balance_after_pence for entry in entries] == [450, 500]
    assert [entry.occurred_on for entry in entries] == [PAYDAY, PAYDAY]

    # And each week records its share.
    session.expire_all()
    assert session.get(Week, first.id).deposited_pence == 450
    assert session.get(Week, second.id).deposited_pence == 50


def test_what_the_child_keeps_is_not_recorded_anywhere(api, session, beds):
    week = settled_week(api, session, beds)
    body = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 100},
    ).json()
    assert body["kept_pence"] == 350

    # Reported, and stored nowhere. Cash in a pocket is not this app's
    # business, and a figure for it would be wrong within a day.
    assert session.query(SavingsEntry).count() == 1
    assert session.query(SavingsEntry).one().amount_pence == 100
    session.expire_all()
    assert session.get(Week, week.id).deposited_pence == 100


def test_depositing_nothing_writes_no_savings_entry(api, session, beds):
    week = settled_week(api, session, beds)
    api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 0},
    )
    assert session.query(SavingsEntry).count() == 0
    session.expire_all()
    assert session.get(Week, week.id).deposited_pence == 0
    assert session.get(Week, week.id).paid_at is not None


def test_depositing_the_whole_payment_is_allowed(api, session, beds):
    week = settled_week(api, session, beds)
    body = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 450},
    ).json()
    assert body["kept_pence"] == 0
    assert body["savings_balance_pence"] == 450


def test_more_cannot_be_deposited_than_was_paid(api, session, beds):
    week = settled_week(api, session, beds)
    response = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 451},
    )
    assert response.status_code == 409

    session.expire_all()
    assert session.get(Week, week.id).paid_at is None   # nothing was applied
    assert session.query(SavingsEntry).count() == 0


def test_a_failing_payment_marks_no_week_paid(api, session, beds):
    first = settled_week(api, session, beds)
    second = Week(start_date=SECOND_SUNDAY, end_date=SECOND_SATURDAY)  # still open
    session.add(second)
    session.commit()

    response = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [first.id, second.id], "deposited_pence": 0},
    )
    assert response.status_code == 409

    session.expire_all()
    assert session.get(Week, first.id).paid_at is None


# --- 4. The opening balance -------------------------------------------------


def test_an_opening_balance_is_recorded_once(api, session):
    response = api.post(
        "/api/savings/opening-balance",
        json={"pin": PIN, "amount_pence": 1500, "occurred_on": FIRST_SUNDAY.isoformat()},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["entry_type"] == "opening_balance"
    assert body["amount_pence"] == 1500
    assert body["balance_after_pence"] == 1500

    assert api.get("/api/savings").json()["balance_pence"] == 1500


def test_an_opening_balance_cannot_be_recorded_twice(api, session):
    body = {"pin": PIN, "amount_pence": 1500}
    assert api.post("/api/savings/opening-balance", json=body).status_code == 201
    again = api.post("/api/savings/opening-balance", json=body)
    assert again.status_code == 409
    assert "recorded once" in again.json()["detail"]


def test_an_opening_balance_cannot_follow_a_deposit(api, session, beds):
    # Everything after it is a movement from a balance, so a starting point
    # inserted afterwards would make every balance recorded before it wrong.
    week = settled_week(api, session, beds)
    api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 100},
    )
    response = api.post("/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 1500})
    assert response.status_code == 409


def test_an_opening_balance_needs_the_pin(api, session):
    response = api.post(
        "/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 1500}
    )
    assert response.status_code == 401
    assert session.query(SavingsEntry).count() == 0


def test_deposits_build_on_the_opening_balance(api, session, beds):
    api.post(
        "/api/savings/opening-balance",
        json={"pin": PIN, "amount_pence": 1500, "occurred_on": FIRST_SUNDAY.isoformat()},
    )
    week = settled_week(api, session, beds)
    body = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 200},
    ).json()

    assert body["savings_balance_pence"] == 1700
    ledger = api.get("/api/savings").json()
    assert [entry["balance_after_pence"] for entry in ledger["entries"]] == [1500, 1700]


def test_the_ledger_is_kept_although_nothing_reads_it_yet(api, session, beds):
    # No match is computed anywhere in this app. The record is kept from the
    # first payday regardless, because a match on money left alone cannot be
    # reconstructed later from figures nobody wrote down.
    week = settled_week(api, session, beds)
    api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 300, "occurred_on": PAYDAY.isoformat()},
    )
    entry = session.query(SavingsEntry).one()
    assert entry.occurred_on == PAYDAY          # when
    assert entry.amount_pence == 300            # how much
    assert entry.balance_after_pence == 300     # and what it came to
    assert entry.week_id == week.id             # and where it came from


# --- 5. Parent-entered rewards ----------------------------------------------


def test_a_reward_carries_an_amount_and_a_reason(api, session):
    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()

    response = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 250,
            "reason": "Helped a neighbour with the shopping",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["amount_pence"] == 250
    assert body["amount"] == "£2.50"
    assert body["reason"] == "Helped a neighbour with the shopping"
    assert body["week_id"] == week.id


def test_a_reward_may_be_typed_as_pounds(api, session):
    session.add(Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY))
    session.commit()
    body = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount": "£1.50",
            "reason": "Tidied the garage",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    ).json()
    assert body["amount_pence"] == 150


def test_a_reward_needs_the_pin_and_a_reason(api, session):
    session.add(Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY))
    session.commit()

    unauthorised = api.post(
        "/api/rewards",
        json={"pin": WRONG, "amount_pence": 100, "reason": "Because"},
    )
    assert unauthorised.status_code == 401

    unreasoned = api.post("/api/rewards", json={"pin": PIN, "amount_pence": 100, "reason": ""})
    assert unreasoned.status_code == 422

    assert session.query(EarningEntry).count() == 0


def test_a_reward_belongs_to_the_week_it_was_entered_in(api, session):
    first = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    second = Week(start_date=SECOND_SUNDAY, end_date=SECOND_SATURDAY)
    session.add_all([first, second])
    session.commit()

    entered_in_the_second = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 100,
            "reason": "Good report",
            "occurred_on": date(2026, 8, 26).isoformat(),
        },
    ).json()
    assert entered_in_the_second["week_id"] == second.id


def test_a_reward_is_independent_of_the_chore_result(api, session, beds):
    # A terrible week: nothing done, no chore pay. The reward is untouched by
    # any of that, and does not change the week's settled figures either.
    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()
    for offset in range(7):
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(FIRST_SUNDAY.toordinal() + offset),
            )
        )
    session.commit()

    api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 250,
            "reason": "Award at school",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    )

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert proposal["chore_pay_pence"] == 0
    assert proposal["reward_pence"] == 0     # not a chore, not in the assessment
    assert proposal["total_pence"] == 100    # the base, and nothing else

    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 100})

    # But the week still owes it, because it was earned.
    (owed,) = api.get("/api/weeks/owed/outstanding").json()
    assert owed["settled_total_pence"] == 100
    assert owed["reward_pence"] == 250
    assert owed["owed_pence"] == 350


def test_a_reward_survives_the_week_being_voided(api, session, beds):
    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()
    api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 250,
            "reason": "Award at school",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    )
    api.post(f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": "Grounded"})

    (owed,) = api.get("/api/weeks/owed/outstanding").json()
    assert owed["settled_total_pence"] == 0   # the week itself pays nothing
    assert owed["owed_pence"] == 250          # the reward stands


def test_a_reward_is_paid_with_the_week_it_belongs_to(api, session, beds):
    # Entered while the week is open, so it belongs to that week and goes out
    # with the same payment.
    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()
    reward = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 250,
            "reason": "Award at school",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    ).json()
    assert reward["week_id"] == week.id
    assert reward["carried_to_an_open_week"] is False

    for offset in range(7):
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(FIRST_SUNDAY.toordinal() + offset),
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
        )
    session.commit()
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    body = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 700},
    ).json()
    assert body["paid_pence"] == 700   # 450 settled + 250 reward
    assert body["deposited_pence"] == 700
    assert body["kept_pence"] == 0


# --- A reward entered for a week that has already settled -------------------


def test_a_reward_for_a_settled_week_is_carried_to_an_open_one(api, session, beds):
    # A settled week is closed forever and cannot take it. The money does not
    # vanish and does not attach to the closed week: it goes to the next open
    # week, and he gets it with that week's money.
    settled = settled_week(api, session, beds)
    later = Week(start_date=SECOND_SUNDAY, end_date=SECOND_SATURDAY)
    session.add(later)
    session.commit()

    body = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 300,
            "reason": "Eagle award",
            "occurred_on": date(2026, 8, 18).isoformat(),  # inside the settled week
        },
    ).json()

    assert body["week_id"] == later.id
    assert body["week_start_date"] == SECOND_SUNDAY.isoformat()
    assert body["carried_to_an_open_week"] is True
    assert body["occurred_on"] == "2026-08-18"  # when it happened is unchanged

    # The settled week is untouched, and still worth what it settled for.
    session.expire_all()
    assert session.get(Week, settled.id).settled_total_pence == 450
    outstanding = {
        owed["week_id"]: owed
        for owed in api.get("/api/weeks/owed/outstanding").json()
    }
    assert outstanding[settled.id]["owed_pence"] == 450


def test_a_reward_for_a_settled_week_opens_one_if_there_is_none(api, session, beds):
    # Nothing else is open. Rather than attach to a closed week or to nothing,
    # a week is opened after the latest on record and the reward waits there.
    settled = settled_week(api, session, beds)

    body = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 300,
            "reason": "Eagle award",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    ).json()

    assert body["carried_to_an_open_week"] is True
    assert body["week_id"] != settled.id
    assert body["week_start_date"] == SECOND_SUNDAY.isoformat()

    session.expire_all()
    carried = session.get(Week, body["week_id"])
    assert carried.status is WeekStatus.OPEN
    assert carried.start_date == SECOND_SUNDAY


def test_a_carried_reward_is_still_paid(api, session, beds):
    # The point of carrying it: the money stays owed and is eventually handed
    # over, which is the one thing that must not fail here.
    settled_week(api, session, beds)
    body = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 300,
            "reason": "Eagle award",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    ).json()
    carried_id = body["week_id"]

    api.post(
        f"/api/weeks/{carried_id}/settle", json={"pin": PIN, "agreed_total_pence": 100}
    )
    outstanding = {
        owed["week_id"]: owed
        for owed in api.get("/api/weeks/owed/outstanding").json()
    }
    assert outstanding[carried_id]["reward_pence"] == 300
    assert outstanding[carried_id]["owed_pence"] == 400  # 100 base + the award


def test_a_reward_never_attaches_to_a_closed_week(api, session, beds):
    # Including a voided one: closed is closed, whichever way it closed.
    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()
    api.post(f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": "Away"})

    body = api.post(
        "/api/rewards",
        json={
            "pin": PIN,
            "amount_pence": 300,
            "reason": "Eagle award",
            "occurred_on": date(2026, 8, 18).isoformat(),
        },
    ).json()
    assert body["week_id"] != week.id
    assert body["carried_to_an_open_week"] is True


def test_a_reward_never_creates_a_second_week_for_the_same_dates(api, session, beds):
    settled_week(api, session, beds)
    for _ in range(3):
        api.post(
            "/api/rewards",
            json={
                "pin": PIN,
                "amount_pence": 300,
                "reason": "Eagle award",
                "occurred_on": date(2026, 8, 18).isoformat(),
            },
        )
    starts = [week.start_date for week in session.query(Week).all()]
    assert len(starts) == len(set(starts)) == 2


# --- 6. The preset ----------------------------------------------------------


def test_the_eagle_award_preset_is_offered(api):
    presets = api.get("/api/rewards/presets").json()
    assert {preset["key"] for preset in presets} == {"eagle_award"}
    assert presets[0]["name"] == "Eagle award"
    assert presets[0]["amount_pence"] == 300
    assert presets[0]["amount"] == "£3.00"


def test_the_preset_records_the_award_without_retyping_it(api, session):
    session.add(Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY))
    session.commit()

    body = api.post(
        "/api/rewards/presets/eagle_award",
        json={"pin": PIN, "occurred_on": date(2026, 8, 18).isoformat()},
    ).json()
    assert body["amount_pence"] == 300
    # The name is the reason, because it is what he calls it and what makes
    # the ledger readable a year later.
    assert body["reason"] == "Eagle award"


def test_the_preset_amount_is_fixed_and_a_different_one_is_refused(api, session):
    session.add(Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY))
    session.commit()

    for attempt in ({"amount": "£2.00"}, {"amount_pence": 200}):
        response = api.post(
            "/api/rewards/presets/eagle_award", json={"pin": PIN, **attempt}
        )
        # Refused rather than ignored: quietly substituting a different number
        # for the one that was asked for is worse than saying no.
        assert response.status_code == 422

    assert session.query(EarningEntry).count() == 0


def test_the_award_may_be_given_any_number_of_times(api, session):
    # The school decides how often it hands one out; the scheme pays for each.
    session.add(Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY))
    session.commit()

    for _ in range(4):
        response = api.post(
            "/api/rewards/presets/eagle_award",
            json={"pin": PIN, "occurred_on": date(2026, 8, 18).isoformat()},
        )
        assert response.status_code == 201

    entries = session.query(EarningEntry).all()
    assert len(entries) == 4
    assert sum(entry.amount_pence for entry in entries) == 1200


def test_the_preset_needs_the_pin(api, session):
    session.add(Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY))
    session.commit()
    response = api.post("/api/rewards/presets/eagle_award", json={"pin": WRONG})
    assert response.status_code == 401


def test_an_unknown_preset_is_a_404(api):
    assert api.post("/api/rewards/presets/nonsense", json={"pin": PIN}).status_code == 404


# --- Every amount is integer pence ------------------------------------------


def test_every_amount_written_today_is_an_integer_number_of_pence(api, session, beds):
    week = settled_week(api, session, beds)
    api.post(
        "/api/rewards",
        json={"pin": PIN, "amount": "£2.50", "reason": "Award", "occurred_on": date(2026, 8, 18).isoformat()},
    )
    api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": 300},
    )

    for entry in session.query(EarningEntry).all():
        assert isinstance(entry.amount_pence, int)
    for entry in session.query(SavingsEntry).all():
        assert isinstance(entry.amount_pence, int)
        assert isinstance(entry.balance_after_pence, int)
    session.expire_all()
    assert isinstance(session.get(Week, week.id).deposited_pence, int)
