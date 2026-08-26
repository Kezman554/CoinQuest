"""The summary endpoint, asserted whole.

The payload is a contract with something outside this repository — a tile on a
dashboard that will not be updated when this app is. So these tests assert the
*whole* object rather than picking at fields: a key quietly added, renamed or
dropped is exactly the change that breaks a consumer, and a test that only
checks the fields it cares about would not notice.

Three weeks, as the card asks: a clean one, one with a recovery outstanding,
and the last day of one.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import Cadence, Category, ChoreDefinition, Week
from app.services.calendar import current_week

PIN = "0000"

#: Every key the tile is entitled to. Asserted as a set so an addition is
#: caught here, where somebody has to think about the consumer, rather than in
#: a house on a wall panel.
FIELDS = {
    "week_start",
    "week_end",
    "status",
    "projected_total_pence",
    "projected_total",
    "recovery_outstanding",
    "recovery_deadline",
    "days_remaining",
}


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


@pytest.fixture()
def scheme(session) -> dict[str, ChoreDefinition]:
    definitions = {
        "bed": ChoreDefinition(
            name="Make your bed",
            cadence=Cadence.DAILY,
            category=Category.BASIC,
            amount_pence=50,
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
    session.commit()
    return definitions


def summary(api) -> dict:
    response = api.get("/api/summary")
    assert response.status_code == 200, response.text
    return response.json()


def open_week(api) -> dict:
    response = api.post("/api/week/open")
    assert response.status_code == 200, response.text
    return response.json()


def instances(view: dict) -> list[dict]:
    cards = [chore for day in view["days"] for chore in day["chores"]]
    for card in view["weekly"]:
        cards.extend(card["instances"])
    return cards


def confirm(api, instance_id: int) -> None:
    assert api.post("/api/claims", json={"instance_id": instance_id}).status_code == 200
    assert (
        api.post(
            "/api/claims/review",
            json={
                "pin": PIN,
                "decisions": [{"instance_id": instance_id, "decision": "confirm"}],
            },
        ).status_code
        == 200
    )


# --- 1. A clean week --------------------------------------------------------


def test_a_clean_week(api, scheme, week_dates, session):
    """Nothing missed, nothing outstanding, no deadline to state.

    Nothing ruled against the week yet either, so it is on track for the
    base and the whole chore pot — not the base alone. The chore pay counts
    as earned until something says otherwise, and silence is not that.
    """
    from app.services import scheme_settings

    start, end = week_dates
    open_week(api)

    payload = summary(api)

    assert set(payload) == FIELDS
    assert payload["week_start"] == start.isoformat()
    assert payload["week_end"] == end.isoformat()
    assert payload["status"] == "open"
    assert payload["recovery_outstanding"] is False
    assert payload["recovery_deadline"] is None
    assert payload["days_remaining"] >= 0
    assert isinstance(payload["projected_total_pence"], int)
    assert payload["projected_total_pence"] == (
        get_settings().weekly_base_pence
        + scheme_settings.weekly_basic_pay_pence(session)
    )


def test_a_week_nothing_has_happened_in_still_answers(api, scheme, session):
    """No week row yet, and the tile still gets a payload rather than a 404.

    A tile that errors every Sunday morning until somebody opens the app is a
    tile nobody trusts by the third week. The figure is the base allowance,
    which is exactly what a freshly opened week proposes.
    """
    assert session.query(Week).count() == 0

    payload = summary(api)

    assert set(payload) == FIELDS
    assert payload["status"] == "not_started"
    assert payload["projected_total_pence"] == get_settings().weekly_base_pence
    assert payload["recovery_outstanding"] is False
    assert payload["recovery_deadline"] is None
    # And asking did not bring a week into being.
    assert session.query(Week).count() == 0


def test_the_total_follows_the_week(api, scheme, week_dates):
    """The tile's figure is the one the child's screen shows him."""
    view = open_week(api)
    bonus = next(
        card for card in instances(view) if card["name"] == "Wash the car"
    )
    confirm(api, bonus["instance_id"])

    payload = summary(api)
    week = api.get("/api/week").json()

    assert payload["projected_total_pence"] == week["totals"]["payable_total_pence"]
    # Written by app.services.money, which is the one place currency is
    # rendered on this side. A tile showing "£4.00" beside a screen showing
    # "£4" is not a disagreement about the money. Base (£1) + the whole,
    # still-on-track chore pot (£2, nothing ruled against it) + the
    # confirmed bonus (£1).
    assert payload["projected_total"] == "£4.00"


def test_a_reward_is_in_the_figure(api, scheme, week_dates):
    """What he will be handed, not what the week will settle at."""
    open_week(api)
    before = summary(api)["projected_total_pence"]

    assert (
        api.post(
            "/api/rewards",
            json={"pin": PIN, "amount_pence": 300, "reason": "Eagle award"},
        ).status_code
        == 201
    )

    assert summary(api)["projected_total_pence"] == before + 300


# --- 2. A recovery outstanding ----------------------------------------------


def test_a_week_with_a_recovery_outstanding(api, scheme, week_dates):
    start, end = week_dates
    view = open_week(api)
    bed = next(
        card
        for card in instances(view)
        if card["due_date"] == start.isoformat()
    )

    assert (
        api.post(
            f"/api/instances/{bed['instance_id']}/missed",
            json={"pin": PIN, "instance_id": bed["instance_id"]},
        ).status_code
        == 200
    )

    payload = summary(api)

    assert set(payload) == FIELDS
    assert payload["recovery_outstanding"] is True
    assert payload["recovery_deadline"] == end.isoformat()
    assert payload["status"] == "open"


def test_working_the_recovery_clears_the_flag(api, scheme, week_dates):
    """And the deadline goes with it: there is nothing left to be by."""
    start, _ = week_dates
    view = open_week(api)
    bed = next(
        card for card in instances(view) if card["due_date"] == start.isoformat()
    )
    api.post(
        f"/api/instances/{bed['instance_id']}/missed",
        json={"pin": PIN, "instance_id": bed["instance_id"]},
    )
    assert summary(api)["recovery_outstanding"] is True

    car = next(card for card in instances(view) if card["name"] == "Wash the car")
    confirm(api, car["instance_id"])

    payload = summary(api)
    assert payload["recovery_outstanding"] is False
    assert payload["recovery_deadline"] is None


def test_the_flag_means_what_the_childs_screen_means(api, scheme, week_dates):
    """One definition of outstanding, in one place, read by both."""
    start, _ = week_dates
    view = open_week(api)
    bed = next(
        card for card in instances(view) if card["due_date"] == start.isoformat()
    )
    api.post(
        f"/api/instances/{bed['instance_id']}/missed",
        json={"pin": PIN, "instance_id": bed["instance_id"]},
    )

    payload = summary(api)
    recovery = api.get("/api/week").json()["recovery"]

    assert payload["recovery_outstanding"] == (recovery["outstanding"] > 0)
    assert payload["recovery_deadline"] == recovery["deadline"]


# --- 3. The last day --------------------------------------------------------


def test_the_last_day_of_a_week(session, scheme, week_dates):
    """Saturday evening: the deadline is today, and no days are left.

    Driven through the service with the clock supplied, because the point is
    what the figure says on a particular evening and the test cannot wait for
    one.
    """
    from app.services import summary as summary_service

    start, end = week_dates
    tz = get_settings().tzinfo
    session.add(Week(start_date=start, end_date=end))
    session.commit()

    saturday_evening = datetime(end.year, end.month, end.day, 20, 0, tzinfo=tz)
    result = summary_service.summarise(session, tz, now=saturday_evening)

    assert result.days_remaining == 0
    assert result.week_end == end

    # And earlier in the same week the count is whole days, not a rounding of
    # part-days: Sunday morning of a seven-day week has six days after it.
    sunday_morning = datetime(start.year, start.month, start.day, 9, 0, tzinfo=tz)
    assert summary_service.summarise(session, tz, now=sunday_morning).days_remaining == 6


def test_days_remaining_never_goes_negative(session, scheme, week_dates):
    """Past the end of the week, before anything has rolled over."""
    from app.services import summary as summary_service

    start, end = week_dates
    tz = get_settings().tzinfo
    session.add(Week(start_date=start, end_date=end))
    session.commit()

    after = datetime(end.year, end.month, end.day, 23, 59, tzinfo=tz) + timedelta(hours=2)
    assert summary_service.summarise(session, tz, now=after).days_remaining == 0


def test_the_last_day_still_states_the_deadline(session, scheme, week_dates):
    """Urgency is the consumer's to present; the facts to present it are here."""
    from app.models import ChoreInstance, InstanceState, MissOrigin
    from app.models.base import utcnow
    from app.services import summary as summary_service

    start, end = week_dates
    tz = get_settings().tzinfo
    week = Week(start_date=start, end_date=end)
    session.add(week)
    session.commit()

    session.add(
        ChoreInstance(
            definition_id=scheme["bed"].id,
            week_id=week.id,
            due_date=start,
            state=InstanceState.MISSED,
            missed_at=utcnow(),
            miss_origin=MissOrigin.PARENT_MARKED,
            authorised_by="parent",
        )
    )
    session.commit()

    result = summary_service.summarise(
        session, tz, now=datetime(end.year, end.month, end.day, 20, 0, tzinfo=tz)
    )

    assert result.recovery_outstanding is True
    assert result.recovery_deadline == end
    assert result.days_remaining == 0


# --- 4. A closed week, and what the payload never carries -------------------


def test_a_settled_week_reads_from_its_own_figures(api, scheme, week_dates):
    view = open_week(api)
    # The figure to settle at is the true, pessimistic proposal — not the
    # child's on-track screen, which reads optimistically and may honestly
    # differ from it. See app.services.settlement.propose's for_display.
    total = api.get(f"/api/weeks/{view['week_id']}/proposal").json()["total_pence"]
    assert (
        api.post(
            f"/api/weeks/{view['week_id']}/settle",
            json={"pin": PIN, "agreed_total_pence": total},
        ).status_code
        == 200
    )

    payload = summary(api)

    assert set(payload) == FIELDS
    assert payload["status"] == "settled"
    assert payload["projected_total_pence"] == total
    # Nothing is outstanding in a week that is over.
    assert payload["recovery_outstanding"] is False
    assert payload["recovery_deadline"] is None


def test_a_voided_week_reads_as_nothing(api, scheme, week_dates):
    view = open_week(api)
    assert (
        api.post(
            f"/api/weeks/{view['week_id']}/void",
            json={"pin": PIN, "reason": "Chickenpox"},
        ).status_code
        == 200
    )

    payload = summary(api)
    assert payload["status"] == "voided"
    assert payload["projected_total_pence"] == 0
    # And not the reason. A glance does not need it and the tile is on a wall.
    assert set(payload) == FIELDS


def test_the_payload_carries_nothing_about_authorisation_or_chores(
    api, scheme, week_dates
):
    """The two things the card rules out, asserted rather than assumed."""
    start, _ = week_dates
    view = open_week(api)
    bed = next(
        card for card in instances(view) if card["due_date"] == start.isoformat()
    )
    api.post(
        f"/api/instances/{bed['instance_id']}/missed",
        json={"pin": PIN, "instance_id": bed["instance_id"]},
    )

    body = api.get("/api/summary").text.lower()

    for word in ("pin", "parent", "authorised", "locked", "attempt"):
        assert word not in body

    # No chore-level detail: not the name of the chore that was missed, not an
    # instance id, not a count of anything per chore.
    for word in ("make your bed", "wash the car", "instance", "definition", "chore"):
        assert word not in body

    assert set(api.get("/api/summary").json()) == FIELDS


def test_reading_the_summary_needs_no_credential_and_changes_nothing(
    api, scheme, session
):
    open_week(api)
    before = summary(api)

    for _ in range(3):
        assert api.get("/api/summary").status_code == 200

    assert summary(api) == before
    assert api.get("/api/week").json()["totals"]["payable_total_pence"] == (
        before["projected_total_pence"]
    )
