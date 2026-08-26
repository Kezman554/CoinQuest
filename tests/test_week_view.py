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
    """No PIN. See app/routers/claims.py for the rule and why it reversed."""
    response = api.post(
        f"/api/instances/{instance_id}/missed",
        json={"instance_id": instance_id},
    )
    assert response.status_code == 200, response.text


def clear_miss(api, instance_id: int) -> None:
    """The guarded direction: this one gives money back."""
    response = api.post(
        f"/api/instances/{instance_id}/missed/clear",
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
    """The case the screen was built for, read end to end.

    Also the card's own test plan for the "on track" fix: a fresh week, a
    confirmed miss, a make-good, and settlement, with the displayed figure
    checked against the settlement proposal at each step that matters.
    """
    start, end = week_dates
    view = open_week(api)

    # A fresh week, nothing touched yet: on track for the base and the whole
    # chore pot. Nothing has been ruled against it, so nothing is deducted —
    # this is the figure the "on track" fix exists to produce.
    assert view["totals"]["chore_pay_pence"] == 50 + 90
    assert view["totals"]["chore_pay_awarded"] is True
    assert view["totals"]["total_pence"] == get_settings().weekly_base_pence + 50 + 90

    mark_missed(api, find_day(view, start)["chores"][0]["instance_id"])
    view = api.get("/api/week").json()

    assert view["recovery"]["outstanding"] == 1
    assert view["recovery"]["deadline"] == end.isoformat()
    assert view["recovery"]["options"][0]["name"] == "Wash the car"
    assert find_day(view, waived_day)["waived"] is True

    # A miss nothing covers fails the chore pay entirely — which is the whole
    # reason the recovery route exists, and what the screen has to make plain.
    # This one is a parent's own ruling, not silence, so it counts even before
    # the week is over.
    assert view["totals"]["chore_pay_pence"] == 0
    assert view["totals"]["chore_pay_awarded"] is False

    car = next(card for card in view["weekly"] if card["name"] == "Wash the car")
    confirm(api, car["instances"][0]["instance_id"])
    view = api.get("/api/week").json()

    assert view["recovery"]["outstanding"] == 0
    assert view["recovery"]["covered"] == 1
    assert view["recovery"]["needs"][0]["covered_by"] == "Wash the car"
    assert [card["name"] for card in view["recovery"]["spent"]] == ["Wash the car"]

    # The one ruled miss is now covered, and the rest of the week — five more
    # days of bed-making, three hoovers, nothing ruled against any of them —
    # is on track rather than presumed lost. 140p of chore pay for 100p of
    # bonus given up, said plainly as held back rather than simply vanished.
    assert view["totals"]["chore_pay_awarded"] is True
    assert view["totals"]["chore_pay_pence"] == 50 + 90
    assert view["totals"]["bonus_pence"] == 0
    assert view["totals"]["held_as_makegood_pence"] == 100
    assert view["totals"]["total_pence"] == get_settings().weekly_base_pence + 50 + 90

    # Work the rest of the week for real.
    for day in view["days"]:
        for chore in day["chores"]:
            if chore["can_claim"]:
                confirm(api, chore["instance_id"])
    hoover = next(card for card in view["weekly"] if card["name"] == "Hoover downstairs")
    for instance in hoover["instances"]:
        confirm(api, instance["instance_id"])

    view = api.get("/api/week").json()

    # Now the ruled miss is the week's only shortfall, genuinely, and the
    # figure has not moved: what was on track is what actually happened.
    assert view["totals"]["chore_pay_awarded"] is True
    assert view["totals"]["chore_pay_pence"] == 50 + 90
    assert view["totals"]["bonus_pence"] == 0
    assert view["totals"]["total_pence"] == (
        get_settings().weekly_base_pence + 50 + 90
    )

    # And it agrees with what settlement would actually pay right now — the
    # optimistic screen and the pessimistic proposal, over the same, now
    # genuinely-finished week.
    settlement_proposal = api.get(f"/api/weeks/{view['week_id']}/proposal").json()
    assert settlement_proposal["total_pence"] == view["totals"]["total_pence"]
    assert settlement_proposal["chore_pay_pence"] == view["totals"]["chore_pay_pence"]


def test_a_week_long_condition_counts_against_the_week_until_it_is_judged(
    api, scheme, condition
):
    """A known gap, recorded rather than worked around — and half-cured by
    the "on track" fix, which is worth being precise about.

    A WEEKLY_CONDITION produces no instance, so there is nothing to claim and
    nothing to confirm, and no route exists by which anybody could rule it
    either way. `assess_week`'s default (pessimistic, for-settling) scoring
    still counts it required-and-unconfirmed from the first minute of the
    week — that half of the gap is untouched here, and Session I's own
    finding still holds against `settle()`: the optimiser quietly spends a
    completed bonus chore covering a miss nobody can clear or even see ruled.

    What changed is the screen. `for_display` scoring never infers a miss
    from silence — only a parent's own ruling counts, and nobody can rule a
    condition at all — so the child's own figures no longer show the bonus
    being eaten by a miss he was never told about. The chore pay reads earned
    and the bonus reads paid, which is honest about what the child can see
    happening, even though the two proposals now disagree about this week
    until settlement actually judges the condition.

    The fix for the condition itself still belongs with the parent view,
    where the judgement would be made.
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

    # The screen reads the week as fully earned: the condition costs nothing
    # here because nobody has ruled against it, and "Wash the car" is paid
    # rather than quietly spent.
    assert view["totals"]["chore_pay_pence"] == 50 + 90
    assert view["totals"]["bonus_pence"] == 100
    assert view["totals"]["held_as_makegood_pence"] == 0

    # The gap survives in what settlement would actually do right now: the
    # default, pessimistic proposal still treats the untouched condition as a
    # standing miss and still spends the bonus covering it.
    pessimistic = api.get(f"/api/weeks/{view['week_id']}/proposal").json()
    assert pessimistic["chore_pay_pence"] == 50 + 90
    assert pessimistic["bonus_pence"] == 0


# --- 7. What the endpoints refuse -------------------------------------------


def test_an_unopened_week_says_so_rather_than_showing_an_empty_one(api, scheme):
    response = api.get("/api/week")
    assert response.status_code == 404
    assert "open" in response.json()["detail"]


def test_a_closed_week_is_read_from_its_own_figures_not_rebuilt(api, scheme, session):
    """A voided week, paged back to: read-only, and read from its own record.

    Once a week is closed the view stops asking `propose()` anything —
    voiding zeroes the base, the chore pay and the bonuses, and a
    recomputation from today's chores would show something else the moment a
    chore definition changed. This is what a screen paging back through
    history reads, so it has to be the stored figures, not a rebuild.
    """
    view = open_week(api)
    response = api.post(
        f"/api/weeks/{view['week_id']}/void",
        json={"pin": PIN, "reason": "Half term"},
    )
    assert response.status_code == 200

    closed = api.get(f"/api/week/{view['week_id']}").json()
    assert closed["status"] == "voided"
    assert closed["totals"]["total_pence"] == 0
    assert closed["totals"]["chore_pay_pence"] == 0
    assert closed["totals"]["base_pence"] == 0
    assert closed["totals"]["bonus_pence"] == 0
    assert closed["recovery"]["needs"] == []
    assert closed["recovery"]["options"] == []


# --- 8. Paging back through weeks -------------------------------------------


def test_is_current_tells_the_present_week_from_the_past_apart(
    api, scheme, session, week_dates
):
    """The flag a screen paging back reads to say plainly it is not now."""
    start, end = week_dates
    last_week = Week(
        start_date=start - timedelta(days=7), end_date=end - timedelta(days=7)
    )
    session.add(last_week)
    session.commit()
    api.post(
        f"/api/weeks/{last_week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": get_settings().weekly_base_pence},
    )

    current = open_week(api)
    assert current["is_current"] is True

    past = api.get(f"/api/week/{last_week.id}").json()
    assert past["is_current"] is False
    assert past["status"] == "settled"


def test_paging_back_reaches_a_past_week_that_is_still_open(api, scheme, session, week_dates):
    """A week nobody ever settled stays reachable, and reads as itself."""
    start, end = week_dates
    older = Week(start_date=start - timedelta(days=14), end_date=end - timedelta(days=14))
    session.add(older)
    session.commit()

    current = open_week(api)
    listed = {week["week_id"]: week for week in api.get("/api/weeks").json()}
    assert set(listed) == {older.id, current["week_id"]}
    assert listed[older.id]["status"] == "open"

    view = api.get(f"/api/week/{older.id}").json()
    assert view["is_current"] is False
    assert view["status"] == "open"
    # Still on track for the base and the whole pot — nothing has been ruled
    # against it either, however old it is.
    assert view["totals"]["chore_pay_pence"] == 50 + 90


# --- 8. The tap on the day tile, and the parent-only undo -------------------


def test_marking_a_miss_moves_the_figure_and_clearing_it_moves_it_back(
    api, scheme, week_dates
):
    """The whole loop the day tile exists for, at the figures a screen reads.

    The card's own worked example: a clean week is on track for the base plus
    the whole basic pot; one marked miss takes the pot — all of it, because
    chore pay is all or nothing — and clearing the mark gives it back. Every
    figure here comes from the engine's own for_display proposal; nothing
    subtracts anything.
    """
    start, _ = week_dates
    view = open_week(api)
    base = view["totals"]["base_pence"]
    whole = base + 50 + 90
    assert view["totals"]["payable_total_pence"] == whole

    wednesday = find_day(view, start + timedelta(days=3))
    bed = next(chore for chore in wednesday["chores"] if chore["name"] == "Make your bed")

    mark_missed(api, bed["instance_id"])

    after = api.get("/api/week").json()
    assert after["totals"]["payable_total_pence"] == base
    assert after["totals"]["chore_pay_awarded"] is False
    assert after["recovery"]["outstanding"] == 1

    # And the tile itself says so, with the undo on it.
    marked = next(
        chore
        for chore in find_day(after, start + timedelta(days=3))["chores"]
        if chore["instance_id"] == bed["instance_id"]
    )
    assert marked["state"] == "missed"
    assert marked["miss_origin"] == "parent_marked"
    assert marked["can_claim"] is False

    clear_miss(api, bed["instance_id"])

    back = api.get("/api/week").json()
    assert back["totals"]["payable_total_pence"] == whole
    assert back["recovery"]["outstanding"] == 0
    restored = next(
        chore
        for chore in find_day(back, start + timedelta(days=3))["chores"]
        if chore["instance_id"] == bed["instance_id"]
    )
    assert restored["state"] == "untouched"
    assert restored["can_claim"] is True


def test_the_make_good_line_says_what_to_do_and_what_it_restores(
    api, scheme, week_dates
):
    """One line, and the figure on it is the one the banner would go back to."""
    start, _ = week_dates
    view = open_week(api)
    whole = view["totals"]["payable_total_pence"]

    bed = next(
        chore
        for chore in find_day(view, start + timedelta(days=3))["chores"]
        if chore["name"] == "Make your bed"
    )
    mark_missed(api, bed["instance_id"])

    make_good = api.get("/api/week").json()["recovery"]["make_good"]
    # "Wash the car" is the bonus chore that can be started today, given up
    # unpaid to cover the miss — so the week comes back to what it was worth,
    # with the bonus spent rather than paid.
    assert make_good["names"] == ["Wash the car"]
    assert make_good["restores_to_pence"] == whole


def test_no_route_back_shows_nothing_rather_than_an_empty_encouragement(
    api, scheme, week_dates
):
    """Past the cap, no amount of bonus work recovers the week. So: no line."""
    start, _ = week_dates
    view = open_week(api)

    for offset in range(3):
        bed = next(
            chore
            for chore in find_day(view, start + timedelta(days=offset))["chores"]
            if chore["name"] == "Make your bed"
        )
        mark_missed(api, bed["instance_id"])

    after = api.get("/api/week").json()
    assert after["recovery"]["outstanding"] == 3
    assert after["recovery"]["make_good"] is None


def test_a_clean_week_offers_no_make_good_at_all(api, scheme):
    """Nothing is lost, so there is nothing to put right."""
    open_week(api)
    assert api.get("/api/week").json()["recovery"]["make_good"] is None


def test_nothing_settles_on_the_figure_the_screen_is_showing(api, scheme, week_dates):
    """The guard whose whole job is refusing a settlement nobody read.

    Session U made this screen optimistic, so the number on it is honestly
    allowed to differ from what settlement would actually pay — and marking a
    miss moves the optimistic one without moving the other. Submitting the
    displayed figure has to be refused, and the figure that settles has to be
    the engine's own proposal.
    """
    start, _ = week_dates
    view = open_week(api)
    week_id = view["week_id"]
    displayed = view["totals"]["total_pence"]

    bed = next(
        chore
        for chore in find_day(view, start + timedelta(days=3))["chores"]
        if chore["name"] == "Make your bed"
    )
    mark_missed(api, bed["instance_id"])

    # The screen's figure has moved; the settlement proposal is what it always
    # was — everything untouched is still a prospective miss to it.
    on_screen = api.get("/api/week").json()["totals"]["total_pence"]
    proposal = api.get(f"/api/weeks/{week_id}/proposal").json()
    assert on_screen != displayed

    refused = api.post(
        f"/api/weeks/{week_id}/settle",
        json={"pin": PIN, "agreed_total_pence": displayed},
    )
    assert refused.status_code == 409

    settled = api.post(
        f"/api/weeks/{week_id}/settle",
        json={"pin": PIN, "agreed_total_pence": proposal["total_pence"]},
    )
    assert settled.status_code == 200, settled.text
    # An unrecovered week pays the base and nothing else: the chore pot is
    # all or nothing, and this week did not get it.
    assert settled.json()["total_pence"] == get_settings().weekly_base_pence
