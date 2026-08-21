"""The week as the child's screen reads it.

Driven against a week that contains all three of the things the view exists to
say out loud: a chore a parent has ruled missed, a recovery still available to
put it right, and a day waived rather than merely empty.

Everything goes over HTTP through the real app. The screen is the only client,
so what matters is what the API actually hands it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import (
    Cadence,
    Category,
    ChoreDefinition,
    Week,
    WaiverScope,
    Waiver,
)
from app.services import scheme_settings
from app.services.calendar import current_week, today

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
def week_dates(session) -> tuple[date, date]:
    """This week. The view's own endpoints are about the week we are in."""
    period = current_week(get_settings().tzinfo)
    return period.start, period.end


@pytest.fixture()
def scheme(session, week_dates) -> dict[str, ChoreDefinition]:
    """Four chores, one of each shape the screen has to tell apart.

    "50 + 90" appears throughout this file as the basic chore pay — that is
    the shared pot now, set explicitly below, not a sum of bed's and
    hoover's own (retired) amounts.
    """
    definitions = {
        "bed": ChoreDefinition(
            name="Make your bed",
            cadence=Cadence.DAILY,
            category=Category.BASIC,
            amount_pence=0,
        ),
        "hoover": ChoreDefinition(
            name="Hoover downstairs",
            cadence=Cadence.WEEKLY_COUNT,
            category=Category.BASIC,
            amount_pence=0,
            times_per_week=3,
        ),
        "car": ChoreDefinition(
            name="Wash the car",
            cadence=Cadence.WEEKLY_COUNT,
            category=Category.BONUS,
            amount_pence=100,
            times_per_week=1,
        ),
    }
    session.add_all(definitions.values())
    scheme_settings.get_row(session).weekly_basic_pay_pence = 50 + 90
    session.commit()
    return definitions


@pytest.fixture()
def condition(session, scheme) -> ChoreDefinition:
    """A week-long condition, which is judged once and never claimed.

    Basic, like bed and hoover — a third gate on the same pot, not a fourth
    figure added to it, so it carries no amount of its own either.
    """
    definition = ChoreDefinition(
        name="Keep your room tidy",
        cadence=Cadence.WEEKLY_CONDITION,
        category=Category.BASIC,
        amount_pence=0,
    )
    session.add(definition)
    session.commit()
    return definition


@pytest.fixture()
def waived_day(session, week_dates) -> date:
    """A day away. Not a day nothing was done on."""
    start, _ = week_dates
    day = start + timedelta(days=1)
    session.add(
        Waiver(scope=WaiverScope.DAY, day=day, reason="Away at Grandma's")
    )
    session.commit()
    return day


def open_week(api) -> dict:
    response = api.post("/api/week/open")
    assert response.status_code == 200, response.text
    return response.json()


def find_day(view: dict, day: date) -> dict:
    return next(card for card in view["days"] if card["day"] == day.isoformat())


def mark_missed(api, instance_id: int) -> None:
    response = api.post(
        f"/api/instances/{instance_id}/missed",
        json={"instance_id": instance_id, "pin": PIN},
    )
    assert response.status_code == 200, response.text


def confirm(api, instance_id: int) -> None:
    assert api.post("/api/claims", json={"instance_id": instance_id}).status_code == 200
    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instance_id, "decision": "confirm"}],
        },
    )
    assert response.status_code == 200, response.text


# --- 1. Opening the week, and the two groupings -----------------------------


def test_opening_the_week_is_idempotent(api, scheme, session):
    """The screen calls this on every load. It must not disturb anything."""
    first = open_week(api)
    ids = [
        chore["instance_id"] for day in first["days"] for chore in day["chores"]
    ]

    second = open_week(api)
    again = [
        chore["instance_id"] for day in second["days"] for chore in day["chores"]
    ]

    assert ids == again
    assert len(session.query(Week).all()) == 1


def test_day_chores_and_week_chores_are_grouped_apart(api, scheme, condition):
    """A daily chore belongs to a day. A count belongs to the week."""
    view = open_week(api)

    assert len(view["days"]) == 7
    for day in view["days"]:
        assert [chore["name"] for chore in day["chores"]] == ["Make your bed"]

    weekly = {card["name"]: card for card in view["weekly"]}
    assert set(weekly) == {"Hoover downstairs", "Keep your room tidy", "Wash the car"}

    hoover = weekly["Hoover downstairs"]
    assert hoover["required"] == 3
    assert len(hoover["instances"]) == 3
    assert [instance["sequence"] for instance in hoover["instances"]] == [1, 2, 3]
    assert hoover["judged_at_settlement"] is False

    # A week-long condition has nothing to tap: it is judged once, at
    # settlement, and appears with no instances at all.
    tidy = weekly["Keep your room tidy"]
    assert tidy["judged_at_settlement"] is True
    assert tidy["instances"] == []


def test_the_week_reads_as_the_days_it_has(api, scheme, week_dates):
    start, end = week_dates
    view = open_week(api)

    assert view["start_date"] == start.isoformat()
    assert view["end_date"] == end.isoformat()
    assert view["today"] == today(get_settings().tzinfo).isoformat()
    assert [day["weekday"] for day in view["days"]][0] == "Sunday"
    assert sum(1 for day in view["days"] if day["is_today"]) == 1


# --- 2. Claiming from this page ---------------------------------------------


def test_an_instance_can_be_claimed_from_the_week_view(api, scheme, week_dates):
    view = open_week(api)
    card = find_day(view, week_dates[0])["chores"][0]
    assert card["can_claim"] is True

    response = api.post("/api/claims", json={"instance_id": card["instance_id"]})
    assert response.status_code == 200

    after = find_day(api.get("/api/week").json(), week_dates[0])["chores"][0]
    assert after["state"] == "claimed"
    assert after["can_claim"] is False


def test_a_day_already_past_can_still_be_claimed(api, scheme, week_dates):
    """Untouched is provisional. Yesterday is not lost until the week settles."""
    start, _ = week_dates
    view = open_week(api)

    past = [day for day in view["days"] if day["is_past"] and not day["waived"]]
    for day in past:
        assert all(chore["can_claim"] for chore in day["chores"])


# --- 3. A miss, a recovery, and the deadline --------------------------------


def test_a_ruled_miss_is_outstanding_with_a_deadline(api, scheme, week_dates):
    start, end = week_dates
    view = open_week(api)
    bed = find_day(view, start)["chores"][0]

    mark_missed(api, bed["instance_id"])
    view = api.get("/api/week").json()

    recovery = view["recovery"]
    assert recovery["outstanding"] == 1
    assert recovery["covered"] == 0
    assert recovery["needs"][0]["miss_name"] == "Make your bed"
    assert recovery["needs"][0]["covered_by"] is None
    assert recovery["deadline"] == end.isoformat()
    assert recovery["seconds_remaining"] > 0

    # The bonus chore has not been done, so it is still an option — this is
    # the recovery being available rather than merely theoretical.
    assert [option["name"] for option in recovery["options"]] == ["Wash the car"]

    assert find_day(view, start)["chores"][0]["state"] == "missed"
    assert find_day(view, start)["chores"][0]["miss_origin"] == "parent_marked"


def test_working_the_bonus_covers_the_miss(api, scheme, week_dates):
    start, _ = week_dates
    view = open_week(api)
    mark_missed(api, find_day(view, start)["chores"][0]["instance_id"])

    car = next(card for card in view["weekly"] if card["name"] == "Wash the car")
    confirm(api, car["instances"][0]["instance_id"])

    recovery = api.get("/api/week").json()["recovery"]
    assert recovery["outstanding"] == 0
    assert recovery["covered"] == 1
    assert recovery["needs"][0]["covered_by"] == "Wash the car"
    assert recovery["options"] == []
    assert [card["name"] for card in recovery["spent"]] == ["Wash the car"]


def test_nothing_missed_means_nothing_outstanding(api, scheme):
    """An untouched Thursday is not a miss, and must not be reported as one."""
    view = open_week(api)
    assert view["recovery"]["needs"] == []
    assert view["recovery"]["outstanding"] == 0
    assert view["recovery"]["urgent"] is False


def test_urgency_is_about_the_time_left_not_the_miss(session, scheme, week_dates):
    """The wording changes inside the last day, and only with work to do."""
    from datetime import datetime

    from app.models.weeks import Week
    from app.services import week_view

    start, end = week_dates
    week = session.query(Week).filter(Week.start_date == start).one_or_none()
    if week is None:
        week = Week(start_date=start, end_date=end)
        session.add(week)
        session.commit()

    tz = get_settings().tzinfo
    early = datetime(start.year, start.month, start.day, 9, 0, tzinfo=tz)
    view = week_view.build(session, week, tz, now=early)
    assert view.recovery.seconds_remaining > week_view.URGENT_WITHIN_SECONDS
    assert view.recovery.urgent is False

    late = datetime(end.year, end.month, end.day, 21, 0, tzinfo=tz)
    view = week_view.build(session, week, tz, now=late)
    assert view.recovery.seconds_remaining < week_view.URGENT_WITHIN_SECONDS
    # Still not urgent: there is nothing outstanding to be urgent about.
    assert view.recovery.urgent is False


# --- 4. The projected total -------------------------------------------------


def test_the_total_is_what_the_week_is_on_track_to_pay(api, scheme):
    view = open_week(api)
    totals = view["totals"]

    assert totals["base_pence"] == get_settings().weekly_base_pence
    assert totals["chore_pay_at_stake_pence"] == 50 + 90
    assert totals["total_pence"] == (
        totals["base_pence"]
        + totals["chore_pay_pence"]
        + totals["bonus_pence"]
        + totals["reward_pence"]
    )


def test_the_total_moves_as_the_week_is_worked(api, scheme, week_dates):
    """Confirming the bonus adds its amount, and nothing else changes."""
    before = open_week(api)["totals"]
    car = next(
        card for card in open_week(api)["weekly"] if card["name"] == "Wash the car"
    )
    confirm(api, car["instances"][0]["instance_id"])
    after = api.get("/api/week").json()["totals"]

    assert after["bonus_pence"] == before["bonus_pence"] + 100
    assert after["total_pence"] == before["total_pence"] + 100


# --- 5. A waived day is waived, not absent ----------------------------------


def test_a_waived_day_keeps_its_place_and_says_why(api, scheme, waived_day):
    view = open_week(api)

    assert view["waived_days"] == [waived_day.isoformat()]
    assert len(view["days"]) == 7  # the week is still seven days long

    day = find_day(view, waived_day)
    assert day["waived"] is True
    assert day["waiver_reason"] == "Away at Grandma's"
    # No instance was generated, so there is nothing to have failed to do.
    assert day["chores"] == []


def test_a_waived_day_costs_nothing(api, scheme, waived_day):
    """One day away does not reduce a three-times-a-week count, per the bands."""
    view = open_week(api)

    hoover = next(card for card in view["weekly"] if card["name"] == "Hoover downstairs")
    assert hoover["required"] == 3
    # Six days of bed-making are asked for instead of seven, and the chore pay
    # at stake is unchanged: a waived day removes the occasion, not the chore.
    assert sum(len(day["chores"]) for day in view["days"]) == 6
    assert view["totals"]["chore_pay_at_stake_pence"] == 50 + 90


# --- 6. The whole week, all three things at once ----------------------------


def test_a_week_with_a_miss_a_recovery_and_a_waived_day(api, scheme, waived_day, week_dates):
    """The case the screen was built for, read end to end."""
    start, end = week_dates
    view = open_week(api)

    mark_missed(api, find_day(view, start)["chores"][0]["instance_id"])
    view = api.get("/api/week").json()

    assert view["recovery"]["outstanding"] == 1
    assert view["recovery"]["deadline"] == end.isoformat()
    assert view["recovery"]["options"][0]["name"] == "Wash the car"
    assert find_day(view, waived_day)["waived"] is True

    # A miss nothing covers fails the chore pay entirely — which is the whole
    # reason the recovery route exists, and what the screen has to make plain.
    assert view["totals"]["chore_pay_pence"] == 0
    assert view["totals"]["chore_pay_awarded"] is False

    car = next(card for card in view["weekly"] if card["name"] == "Wash the car")
    confirm(api, car["instances"][0]["instance_id"])
    view = api.get("/api/week").json()

    assert view["recovery"]["outstanding"] == 0
    assert view["recovery"]["covered"] == 1
    assert view["recovery"]["needs"][0]["covered_by"] == "Wash the car"
    assert [card["name"] for card in view["recovery"]["spent"]] == ["Wash the car"]

    # The projected total is still bleak, and correctly so: five days of
    # bed-making and three hoovers have not happened yet, and a projection
    # that assumed they would is not a projection. Work the rest of the week.
    assert view["totals"]["chore_pay_pence"] == 0

    for day in view["days"]:
        for chore in day["chores"]:
            if chore["can_claim"]:
                confirm(api, chore["instance_id"])
    hoover = next(card for card in view["weekly"] if card["name"] == "Hoover downstairs")
    for instance in hoover["instances"]:
        confirm(api, instance["instance_id"])

    view = api.get("/api/week").json()

    # Now the ruled miss is the week's only shortfall, and the bonus worked
    # unpaid buys the chore pay back: 140p of chore pay for 100p of bonus
    # given up, which is why the optimiser takes it.
    assert view["totals"]["chore_pay_awarded"] is True
    assert view["totals"]["chore_pay_pence"] == 50 + 90
    assert view["totals"]["bonus_pence"] == 0
    assert view["totals"]["total_pence"] == (
        get_settings().weekly_base_pence + 50 + 90
    )


def test_a_week_long_condition_counts_against_the_week_until_it_is_judged(
    api, scheme, condition
):
    """Recorded rather than worked around, because this screen makes it visible.

    A WEEKLY_CONDITION produces no instance, so there is nothing to claim and
    nothing to confirm: `assess_week` counts it required-and-not-confirmed from
    the first minute of the week, and no route exists by which anybody could
    make it confirmed. Its shortfall is therefore a standing miss.

    What that costs is not obvious from the figures. The miss is inferred
    rather than ruled, so it appears nowhere in the recovery panel — correctly,
    since there is nothing the child could do about it — while the optimiser
    quietly spends a completed bonus chore covering it. A week in which
    everything was done reads as chore pay in full and the bonus gone.

    The fix belongs with the parent view, where the judgement would be made.
    Until then the frontend labels the card as judged on Sunday, so the figure
    is at least explicable to whoever is reading it.
    """
    view = open_week(api)

    for day in view["days"]:
        for chore in day["chores"]:
            confirm(api, chore["instance_id"])
    for card in view["weekly"]:
        for instance in card["instances"]:
            confirm(api, instance["instance_id"])

    view = api.get("/api/week").json()

    assert all(
        chore["state"] == "confirmed"
        for day in view["days"]
        for chore in day["chores"]
    )
    # Nothing was ruled missed, so the child is told to do nothing — and there
    # is nothing he could do.
    assert view["recovery"]["outstanding"] == 0
    assert view["recovery"]["needs"] == []

    # The condition is still counted against the week, and the bonus paid for
    # it: 100p of "Wash the car" spent, unpaid, on a miss nobody can clear.
    # The pot is flat regardless of how many basic chores gate it — a third
    # one (the condition) does not add its own retired amount on top.
    assert view["totals"]["chore_pay_pence"] == 50 + 90
    assert view["totals"]["bonus_pence"] == 0


# --- 7. What the endpoints refuse -------------------------------------------


def test_an_unopened_week_says_so_rather_than_showing_an_empty_one(api, scheme):
    response = api.get("/api/week")
    assert response.status_code == 404
    assert "open" in response.json()["detail"]


def test_a_closed_week_is_not_rebuilt_from_todays_chores(api, scheme, session):
    view = open_week(api)
    response = api.post(
        f"/api/weeks/{view['week_id']}/void",
        json={"pin": PIN, "reason": "Half term"},
    )
    assert response.status_code == 200

    refused = api.get(f"/api/week/{view['week_id']}")
    assert refused.status_code == 409
    assert "voided" in refused.json()["detail"]
