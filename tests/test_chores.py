"""Creating, listing, editing and retiring chore definitions.

Two cases the card asks for, and they are the point of this file: a chore
created through the API appears on the current week's view without anyone
having to reopen it, and retiring one leaves a week it was already settled in
completely unchanged — no delete, no recomputation, no drift.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import Cadence, Category, ChoreDefinition, ChoreInstance, InstanceState, Week
from app.services.calendar import current_week

PIN = "0000"
WRONG = "9999"
FIRST_SUNDAY = date(2026, 8, 16)
FIRST_SATURDAY = date(2026, 8, 22)


@pytest.fixture()
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def week_dates() -> tuple[date, date]:
    period = current_week(get_settings().tzinfo)
    return period.start, period.end


def create(api, **overrides) -> dict:
    body = {
        "pin": PIN,
        "name": "Water houseplants",
        "category": "bonus",
        "cadence": "weekly_count",
        "times_per_week": 2,
        "amount_pence": 50,
        "is_administered": False,
        **overrides,
    }
    response = api.post("/api/chores", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- Creating ------------------------------------------------------------------


def test_creating_needs_the_pin(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": WRONG,
            "name": "Water houseplants",
            "category": "bonus",
            "cadence": "weekly_count",
            "times_per_week": 2,
            "amount_pence": 50,
        },
    )
    assert response.status_code == 401
    assert api.get("/api/chores").json() == []


def test_a_created_chore_is_available_and_not_administered_by_default(api):
    body = create(api)
    assert body["is_available"] is True
    assert body["is_administered"] is False
    assert body["name"] == "Water houseplants"
    assert body["category"] == "bonus"
    assert body["cadence"] == "weekly_count"
    assert body["times_per_week"] == 2
    assert body["amount_pence"] == 50


def test_an_administered_chore_can_be_marked_so(api):
    body = create(
        api,
        name="Clock test",
        cadence="event",
        times_per_week=None,
        is_administered=True,
    )
    assert body["is_administered"] is True


def test_a_duplicate_name_is_refused(api):
    create(api)
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Water houseplants",
            "category": "basic",
            "cadence": "daily",
            "amount_pence": 10,
        },
    )
    assert response.status_code == 409
    assert len(api.get("/api/chores").json()) == 1


def test_weekly_count_must_state_how_many(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Hoover",
            "category": "basic",
            "cadence": "weekly_count",
            "amount_pence": 90,
        },
    )
    assert response.status_code == 422


def test_only_weekly_count_may_state_how_many(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Make bed",
            "category": "basic",
            "cadence": "daily",
            "times_per_week": 3,
            "amount_pence": 50,
        },
    )
    assert response.status_code == 422


def test_an_unknown_cadence_is_refused(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Bins out",
            "category": "basic",
            "cadence": "specific_weekdays",
            "amount_pence": 20,
        },
    )
    assert response.status_code == 422


def test_a_negative_amount_is_refused(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Make bed",
            "category": "basic",
            "cadence": "daily",
            "amount_pence": -10,
        },
    )
    assert response.status_code == 422


# --- Listing ---------------------------------------------------------------


def test_listing_needs_no_pin(api):
    create(api)
    response = api.get("/api/chores")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_listing_includes_retired_chores(api):
    body = create(api)
    api.post(f"/api/chores/{body['id']}/retire", json={"pin": PIN})
    listed = api.get("/api/chores").json()
    assert len(listed) == 1
    assert listed[0]["is_available"] is False


# --- Editing -----------------------------------------------------------------


def test_editing_needs_the_pin(api):
    body = create(api)
    response = api.post(
        f"/api/chores/{body['id']}",
        json={
            "pin": WRONG,
            "name": "Water plants",
            "category": "bonus",
            "cadence": "weekly_count",
            "times_per_week": 2,
            "amount_pence": 50,
        },
    )
    assert response.status_code == 401


def test_editing_changes_the_rule(api):
    body = create(api)
    response = api.post(
        f"/api/chores/{body['id']}",
        json={
            "pin": PIN,
            "name": "Water houseplants twice",
            "category": "bonus",
            "cadence": "weekly_count",
            "times_per_week": 3,
            "amount_pence": 75,
            "is_administered": False,
        },
    )
    assert response.status_code == 200
    edited = response.json()
    assert edited["name"] == "Water houseplants twice"
    assert edited["times_per_week"] == 3
    assert edited["amount_pence"] == 75


def test_editing_an_unknown_chore_is_404(api):
    response = api.post(
        "/api/chores/999",
        json={
            "pin": PIN,
            "name": "Nothing",
            "category": "basic",
            "cadence": "daily",
            "amount_pence": 10,
        },
    )
    assert response.status_code == 404


def test_editing_cannot_touch_availability(api, session):
    """Retiring is the only way off. Edit does not carry the field at all."""
    body = create(api)
    response = api.post(
        f"/api/chores/{body['id']}",
        json={
            "pin": PIN,
            "name": body["name"],
            "category": body["category"],
            "cadence": body["cadence"],
            "times_per_week": body["times_per_week"],
            "amount_pence": body["amount_pence"],
            "is_available": False,  # not a field the schema accepts; ignored
        },
    )
    assert response.status_code == 200
    definition = session.get(ChoreDefinition, body["id"])
    assert definition.is_available is True


# --- Retiring ------------------------------------------------------------------


def test_retiring_needs_the_pin(api):
    body = create(api)
    response = api.post(f"/api/chores/{body['id']}/retire", json={"pin": WRONG})
    assert response.status_code == 401


def test_retiring_switches_off_rather_than_deletes(api, session):
    body = create(api)
    response = api.post(f"/api/chores/{body['id']}/retire", json={"pin": PIN})
    assert response.status_code == 200
    assert response.json()["is_available"] is False

    # Still there. Retiring is not deleting.
    definition = session.get(ChoreDefinition, body["id"])
    assert definition is not None
    assert definition.is_available is False


def test_retiring_twice_is_refused(api):
    body = create(api)
    api.post(f"/api/chores/{body['id']}/retire", json={"pin": PIN})
    response = api.post(f"/api/chores/{body['id']}/retire", json={"pin": PIN})
    assert response.status_code == 409


def test_retiring_an_unknown_chore_is_404(api):
    response = api.post("/api/chores/999/retire", json={"pin": PIN})
    assert response.status_code == 404


# --- Appearing on the current week's view --------------------------------------


def test_a_created_chore_appears_on_the_current_weeks_view(api, week_dates):
    """The card's first case. No reopening, no extra step."""
    start, end = week_dates
    assert api.post("/api/week/open").status_code == 200

    body = create(api, name="Wipe sides", cadence="weekly_count", times_per_week=3)

    week = api.get("/api/week").json()
    assert week["start_date"] == start.isoformat()
    assert week["end_date"] == end.isoformat()

    weekly_names = {card["name"] for card in week["weekly"]}
    assert "Wipe sides" in weekly_names
    card = next(card for card in week["weekly"] if card["name"] == "Wipe sides")
    assert card["required"] == 3
    assert len(card["instances"]) == 3


def test_a_daily_chore_appears_on_every_day(api):
    assert api.post("/api/week/open").status_code == 200
    create(api, name="Make your bed", category="basic", cadence="daily", times_per_week=None)

    week = api.get("/api/week").json()
    for day in week["days"]:
        names = {chore["name"] for chore in day["chores"]}
        assert "Make your bed" in names


def test_editing_the_current_weeks_chore_reflects_immediately(api):
    assert api.post("/api/week/open").status_code == 200
    body = create(api, name="Wipe sides", cadence="weekly_count", times_per_week=2)

    api.post(
        f"/api/chores/{body['id']}",
        json={
            "pin": PIN,
            "name": "Wipe sides",
            "category": "bonus",
            "cadence": "weekly_count",
            "times_per_week": 3,
            "amount_pence": 50,
        },
    )

    week = api.get("/api/week").json()
    card = next(card for card in week["weekly"] if card["name"] == "Wipe sides")
    assert card["required"] == 3
    assert len(card["instances"]) == 3


def test_retiring_removes_the_untouched_instance_but_not_a_confirmed_one(api):
    assert api.post("/api/week/open").status_code == 200
    body = create(api, name="Wipe sides", cadence="weekly_count", times_per_week=2)

    week = api.get("/api/week").json()
    card = next(card for card in week["weekly"] if card["name"] == "Wipe sides")
    first, second = card["instances"]

    # Claim and confirm one of the two before the chore is retired.
    assert api.post("/api/claims", json={"instance_id": first["instance_id"]}).status_code == 200
    assert (
        api.post(
            "/api/claims/review",
            json={
                "pin": PIN,
                "decisions": [{"instance_id": first["instance_id"], "decision": "confirm"}],
            },
        ).status_code
        == 200
    )

    api.post(f"/api/chores/{body['id']}/retire", json={"pin": PIN})

    week = api.get("/api/week").json()
    # The chore no longer being available means it drops out of the plan
    # entirely — but the confirmed work behind it does not disappear:
    # nothing in this scheme deletes a claim or a confirmation.
    remaining = next(
        (card for card in week["weekly"] if card["name"] == "Wipe sides"), None
    )
    assert remaining is not None
    assert remaining["confirmed"] == 1
    assert len(remaining["instances"]) == 1
    assert remaining["instances"][0]["instance_id"] == first["instance_id"]


# --- The card's second case: a settled week is unaffected ---------------------


def test_retiring_leaves_a_settled_weeks_historical_rows_unchanged(api, session):
    """The card's second case.

    Retiring a chore that a settled week already paid for must not touch that
    week's stored figures or its settlement lines — the same guarantee
    editing already has (test_settlement.py), proved here through the
    retire endpoint specifically.
    """
    definition = ChoreDefinition(
        name="Hoover downstairs",
        cadence=Cadence.WEEKLY_COUNT,
        category=Category.BASIC,
        amount_pence=180,
        times_per_week=2,
    )
    session.add(definition)
    session.commit()

    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()

    session.add_all(
        [
            ChoreInstance(
                definition_id=definition.id,
                week_id=week.id,
                due_date=None,
                sequence=slot,
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
            for slot in (1, 2)
        ]
    )
    session.commit()

    settle = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 280}
    )
    assert settle.status_code == 200, settle.text
    before = api.get(f"/api/weeks/{week.id}").json()

    retire = api.post(f"/api/chores/{definition.id}/retire", json={"pin": PIN})
    assert retire.status_code == 200

    # Repricing the retired chore too, for good measure — the same edit that
    # test_settlement.py already proves is inert against a settled week.
    session.refresh(definition)
    definition.amount_pence = 999
    session.commit()

    after = api.get(f"/api/weeks/{week.id}").json()
    assert after == before

    named = {line["chore_name"]: line for line in after["lines"]}
    assert named["Hoover downstairs"]["unit_amount_pence"] == 180
    assert named["Hoover downstairs"]["amount_pence"] == 180

    # And the definition itself survives, retired rather than gone.
    survivor = session.get(ChoreDefinition, definition.id)
    assert survivor is not None
    assert survivor.is_available is False


# --- The weekdays cadence -------------------------------------------------------


def weekdays_chore(api, **overrides) -> dict:
    fields = {
        "name": "Bins out",
        "category": "basic",
        "cadence": "weekdays",
        "times_per_week": None,
        "weekdays": ["tuesday", "friday"],
        "amount_pence": 50,
        **overrides,
    }
    return create(api, **fields)


def test_a_weekdays_chore_needs_weekdays(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Bins out",
            "category": "basic",
            "cadence": "weekdays",
            "amount_pence": 50,
        },
    )
    assert response.status_code == 422


def test_only_weekdays_may_state_weekdays(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Make bed",
            "category": "basic",
            "cadence": "daily",
            "weekdays": ["tuesday"],
            "amount_pence": 50,
        },
    )
    assert response.status_code == 422


def test_an_unrecognised_weekday_is_refused(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Bins out",
            "category": "basic",
            "cadence": "weekdays",
            "weekdays": ["teusday"],
            "amount_pence": 50,
        },
    )
    assert response.status_code == 422


def test_weekdays_and_times_per_week_together_is_refused(api):
    response = api.post(
        "/api/chores",
        json={
            "pin": PIN,
            "name": "Confused chore",
            "category": "basic",
            "cadence": "weekdays",
            "weekdays": ["tuesday"],
            "times_per_week": 2,
            "amount_pence": 50,
        },
    )
    assert response.status_code == 422


def test_a_weekdays_chore_is_created_with_its_days(api):
    body = weekdays_chore(api)
    assert body["cadence"] == "weekdays"
    assert body["weekdays"] == ["tuesday", "friday"]
    assert body["times_per_week"] is None


def test_weekdays_are_stored_canonically_regardless_of_input_order(api):
    body = weekdays_chore(api, weekdays=["friday", "tuesday"])
    assert body["weekdays"] == ["tuesday", "friday"]


def test_a_weekdays_chores_days_appear_on_exactly_those_days(api, week_dates):
    """The card's first case: created, and due on exactly Tuesday and Friday."""
    start, end = week_dates
    assert api.post("/api/week/open").status_code == 200

    weekdays_chore(api)

    week = api.get("/api/week").json()
    assert week["start_date"] == start.isoformat()
    assert week["end_date"] == end.isoformat()

    due_on = {
        day["weekday"]
        for day in week["days"]
        if any(chore["name"] == "Bins out" for chore in day["chores"])
    }
    assert due_on == {"Tuesday", "Friday"}


def test_editing_a_weekdays_chores_days_reflects_immediately_no_reopen(api):
    body = weekdays_chore(api)
    assert api.post("/api/week/open").status_code == 200

    api.post(
        f"/api/chores/{body['id']}",
        json={
            "pin": PIN,
            "name": "Bins out",
            "category": "basic",
            "cadence": "weekdays",
            "weekdays": ["monday", "wednesday", "saturday"],
            "amount_pence": 50,
        },
    )

    week = api.get("/api/week").json()
    due_on = {
        day["weekday"]
        for day in week["days"]
        if any(chore["name"] == "Bins out" for chore in day["chores"])
    }
    assert due_on == {"Monday", "Wednesday", "Saturday"}


def test_missing_a_weekdays_occurrence_is_recoverable_like_a_daily_one(api):
    """The card's second case: a missed Tuesday, covered like a missed daily chore."""
    assert api.post("/api/week/open").status_code == 200

    weekdays_chore(api)
    create(api)  # the default: "Water houseplants", bonus, 2x a week, 50p

    week = api.get("/api/week").json()
    tuesday = next(
        card
        for day in week["days"]
        if day["weekday"] == "Tuesday"
        for card in day["chores"]
        if card["name"] == "Bins out"
    )

    missed = api.post(
        f"/api/instances/{tuesday['instance_id']}/missed",
        json={"pin": PIN, "instance_id": tuesday["instance_id"]},
    )
    assert missed.status_code == 200, missed.text

    # Complete the bonus chore fully, so it is available to cover the miss.
    week = api.get("/api/week").json()
    houseplants = next(
        card for card in week["weekly"] if card["name"] == "Water houseplants"
    )
    for instance in houseplants["instances"]:
        assert (
            api.post(
                "/api/claims", json={"instance_id": instance["instance_id"]}
            ).status_code
            == 200
        )
        assert (
            api.post(
                "/api/claims/review",
                json={
                    "pin": PIN,
                    "decisions": [
                        {
                            "instance_id": instance["instance_id"],
                            "decision": "confirm",
                        }
                    ],
                },
            ).status_code
            == 200
        )

    week = api.get("/api/week").json()
    recovery = week["recovery"]
    assert recovery["outstanding"] == 0
    assert recovery["covered"] == 1
    (need,) = [n for n in recovery["needs"] if n["miss_name"] == "Bins out"]
    assert need["covered_by"] == "Water houseplants"


def test_a_week_settled_before_this_card_shipped_is_untouched_by_it(api, session):
    """Introducing the cadence must not disturb data that never used it."""
    definition = ChoreDefinition(
        name="Make your bed",
        cadence=Cadence.DAILY,
        category=Category.BASIC,
        amount_pence=350,
    )
    session.add(definition)
    session.commit()

    week = Week(start_date=FIRST_SUNDAY, end_date=FIRST_SATURDAY)
    session.add(week)
    session.commit()

    session.add_all(
        [
            ChoreInstance(
                definition_id=definition.id,
                week_id=week.id,
                due_date=FIRST_SUNDAY + timedelta(days=offset),
                sequence=1,
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
            for offset in range(7)
        ]
    )
    session.commit()

    settle = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert settle.status_code == 200, settle.text
    before = api.get(f"/api/weeks/{week.id}").json()

    # Only now, after that week closed, does the new cadence enter the scheme.
    weekdays_chore(api)

    after = api.get(f"/api/weeks/{week.id}").json()
    assert after == before
