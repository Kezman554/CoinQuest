"""The parent's surface: the queue, the consequence of a batch, and the acts.

The central case is the one a parent actually faces on a Sunday. A week is
failing — something is outstanding, so the chore pay is at stake — and there
is a list of claims in front of them. The question is not "how many items is
this" but "what does agreeing to it do", and the answer has to be the answer:
what the app says the batch will do is compared, field by field, against what
the week is worth once the batch has actually been applied.
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
    ChoreInstance,
    InstanceState,
    Waiver,
    Week,
)
from app.services.calendar import current_week

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
        "hoover": ChoreDefinition(
            name="Hoover downstairs",
            cadence=Cadence.WEEKLY_COUNT,
            category=Category.BASIC,
            amount_pence=90,
            times_per_week=2,
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


def open_week(api) -> dict:
    response = api.post("/api/week/open")
    assert response.status_code == 200, response.text
    return response.json()


def claim(api, instance_id: int) -> None:
    assert api.post("/api/claims", json={"instance_id": instance_id}).status_code == 200


def review(api, decisions: list[dict], pin: str = PIN):
    return api.post("/api/claims/review", json={"pin": pin, "decisions": decisions})


def confirm(api, instance_id: int) -> None:
    claim(api, instance_id)
    assert review(api, [{"instance_id": instance_id, "decision": "confirm"}]).status_code == 200


def every_instance(view: dict) -> list[dict]:
    cards = [chore for day in view["days"] for chore in day["chores"]]
    for card in view["weekly"]:
        cards.extend(card["instances"])
    return cards


@pytest.fixture()
def failing_week(api, scheme) -> dict:
    """A week that pays no chore pay, with one claim still pending.

    Every basic occasion is confirmed except one, which is claimed and
    waiting. While it waits it is not confirmed, so the week is short of its
    requirement and the chore pay — all or nothing — is lost.

    The bonus chore is deliberately left undone. A completed bonus would let
    the optimiser recover the miss on its own, and the week would already be
    passing before the parent touched anything: there would be nothing for the
    batch to rescue and nothing to state a consequence about.
    """
    view = open_week(api)
    cards = [
        card for card in every_instance(view) if card["category"] == "basic"
    ]
    pending = cards[0]

    for card in cards[1:]:
        confirm(api, card["instance_id"])
    claim(api, pending["instance_id"])

    return {"view": view, "pending": pending}


# --- 1. The queue -----------------------------------------------------------


def test_the_queue_holds_what_is_waiting(api, scheme, failing_week):
    queue = api.get("/api/parent/queue").json()

    assert len(queue) == 1
    assert queue[0]["instance_id"] == failing_week["pending"]["instance_id"]
    assert queue[0]["name"] == failing_week["pending"]["name"]
    assert queue[0]["claimed_at"] is not None


def test_the_queue_empties_as_it_is_worked(api, scheme, failing_week):
    instance_id = failing_week["pending"]["instance_id"]
    assert review(api, [{"instance_id": instance_id, "decision": "confirm"}]).status_code == 200
    assert api.get("/api/parent/queue").json() == []


def test_a_rejected_claim_leaves_the_queue_and_says_it_was_refused(
    api, scheme, failing_week
):
    instance_id = failing_week["pending"]["instance_id"]
    assert review(api, [{"instance_id": instance_id, "decision": "reject"}]).status_code == 200
    assert api.get("/api/parent/queue").json() == []

    # Back to untouched and claimable, with the refusal on the record.
    card = next(
        card
        for card in every_instance(api.get("/api/week").json())
        if card["instance_id"] == instance_id
    )
    assert card["state"] == "untouched"
    assert card["can_claim"] is True
    assert card["rejection_count"] == 1


# --- 2. What the batch does, before anybody types a PIN ---------------------


def test_the_consequence_is_stated_in_the_weeks_own_terms(api, scheme, failing_week):
    instance_id = failing_week["pending"]["instance_id"]

    consequences = api.post(
        "/api/parent/review/preview",
        json={"decisions": [{"instance_id": instance_id, "decision": "confirm"}]},
    ).json()

    assert len(consequences) == 1
    effect = consequences[0]

    # Not "1 item": what it does to the week.
    assert effect["before"]["chore_pay_awarded"] is False
    assert effect["after"]["chore_pay_awarded"] is True
    assert effect["rescues_the_chore_pay"] is True
    assert effect["before"]["misses_outstanding"] == 1
    assert effect["after"]["misses_outstanding"] == 0
    assert effect["difference_pence"] == 50 + 90


def test_the_stated_consequence_is_what_actually_happens(api, scheme, failing_week):
    """The case this session exists for. Predicted, then applied, then compared."""
    instance_id = failing_week["pending"]["instance_id"]
    decisions = [{"instance_id": instance_id, "decision": "confirm"}]

    predicted = api.post(
        "/api/parent/review/preview", json={"decisions": decisions}
    ).json()[0]

    assert review(api, decisions).status_code == 200

    actual = api.get(f"/api/weeks/{predicted['week_id']}/proposal").json()

    assert actual["total_pence"] == predicted["after"]["total_pence"]
    assert actual["chore_pay_pence"] == predicted["after"]["chore_pay_pence"]
    assert actual["chore_pay_awarded"] == predicted["after"]["chore_pay_awarded"]
    assert actual["bonus_pence"] == predicted["after"]["bonus_pence"]
    assert actual["reward_pence"] == predicted["after"]["reward_pence"]
    assert actual["misses_outstanding"] == predicted["after"]["misses_outstanding"]
    assert actual["misses"] == predicted["after"]["misses"]
    assert [
        [recovery["miss_name"], recovery["spent_name"]]
        for recovery in actual["recoveries"]
    ] == predicted["after"]["recoveries"]


def test_a_rejection_is_previewed_as_costing_the_week(api, scheme, failing_week):
    instance_id = failing_week["pending"]["instance_id"]

    effect = api.post(
        "/api/parent/review/preview",
        json={"decisions": [{"instance_id": instance_id, "decision": "reject"}]},
    ).json()[0]

    # Refusing the claim leaves the week exactly where it was: still short,
    # still no chore pay. The parent should be able to see that too.
    assert effect["rescues_the_chore_pay"] is False
    assert effect["after"]["chore_pay_awarded"] is False
    assert effect["difference_pence"] == 0
    assert effect["rejected"] == 1
    assert effect["confirmed"] == 0


def test_previewing_changes_nothing(api, scheme, failing_week, session):
    """Applied inside a savepoint and thrown away, twice over."""
    instance_id = failing_week["pending"]["instance_id"]
    decisions = [{"instance_id": instance_id, "decision": "confirm"}]

    before = api.get("/api/week").json()
    api.post("/api/parent/review/preview", json={"decisions": decisions})
    api.post("/api/parent/review/preview", json={"decisions": decisions})
    after = api.get("/api/week").json()

    assert before == after
    assert api.get("/api/parent/queue").json()[0]["instance_id"] == instance_id

    instance = session.get(ChoreInstance, instance_id)
    assert instance.state is InstanceState.CLAIMED
    assert instance.authorised_by is None


def test_a_batch_the_commit_would_refuse_is_refused_by_the_preview(
    api, scheme, failing_week
):
    """Worth knowing before the PIN, and by the same rule that would refuse it."""
    confirmed = next(
        card
        for card in every_instance(api.get("/api/week").json())
        if card["state"] == "confirmed"
    )

    response = api.post(
        "/api/parent/review/preview",
        json={
            "decisions": [{"instance_id": confirmed["instance_id"], "decision": "confirm"}]
        },
    )
    assert response.status_code == 409
    assert "not a pending claim" in response.json()["detail"]

    # And the real submission refuses it the same way.
    assert (
        review(api, [{"instance_id": confirmed["instance_id"], "decision": "confirm"}])
        .status_code
        == 409
    )


def test_the_preview_needs_no_pin_and_the_batch_does(api, scheme, failing_week):
    instance_id = failing_week["pending"]["instance_id"]
    decisions = [{"instance_id": instance_id, "decision": "confirm"}]

    assert (
        api.post("/api/parent/review/preview", json={"decisions": decisions}).status_code
        == 200
    )
    assert review(api, decisions, pin=WRONG).status_code == 401
    assert api.post("/api/claims/review", json={"decisions": decisions}).status_code == 422
    # Nothing moved on either refusal.
    assert api.get("/api/parent/queue").json()[0]["instance_id"] == instance_id


# --- 3. Waiving -------------------------------------------------------------


def test_waiving_a_day_removes_its_untouched_occasions(api, scheme, week_dates, session):
    start, _ = week_dates
    open_week(api)
    day = start + timedelta(days=2)

    response = api.post(
        "/api/waivers",
        json={"pin": PIN, "scope": "day", "day": day.isoformat(), "reason": "Away"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["instances_removed"] == 1

    view = api.get("/api/week").json()
    waived = next(card for card in view["days"] if card["day"] == day.isoformat())
    assert waived["waived"] is True
    assert waived["chores"] == []
    assert view["waived_days"] == [day.isoformat()]


def test_waiving_a_day_leaves_confirmed_work_alone(api, scheme, week_dates):
    """A waiver is not a way to delete somebody's confirmed work."""
    start, _ = week_dates
    view = open_week(api)
    day = start + timedelta(days=2)
    card = next(
        chore
        for chore in every_instance(view)
        if chore["due_date"] == day.isoformat()
    )
    confirm(api, card["instance_id"])

    response = api.post(
        "/api/waivers",
        json={"pin": PIN, "scope": "day", "day": day.isoformat(), "reason": "Away"},
    )
    assert response.status_code == 201
    assert response.json()["instances_removed"] == 0

    waived = next(
        card for card in api.get("/api/week").json()["days"] if card["day"] == day.isoformat()
    )
    assert waived["waived"] is True
    assert [chore["state"] for chore in waived["chores"]] == ["confirmed"]


def test_waiving_a_chore_for_the_week(api, scheme, week_dates):
    view = open_week(api)
    hoover = next(card for card in view["weekly"] if card["name"] == "Hoover downstairs")

    response = api.post(
        "/api/waivers",
        json={
            "pin": PIN,
            "scope": "chore_week",
            "week_id": view["week_id"],
            "definition_id": hoover["definition_id"],
            "reason": "The hoover is broken",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["instances_removed"] == 2

    after = api.get("/api/week").json()
    assert all(card["name"] != "Hoover downstairs" for card in after["weekly"])
    # And the week no longer puts that chore's money at stake.
    assert after["totals"]["chore_pay_at_stake_pence"] == view["totals"][
        "chore_pay_at_stake_pence"
    ] - 90


def test_waiving_needs_the_pin_and_a_coherent_scope(api, scheme, week_dates):
    start, _ = week_dates
    open_week(api)

    assert (
        api.post(
            "/api/waivers",
            json={"pin": WRONG, "scope": "day", "day": start.isoformat()},
        ).status_code
        == 401
    )
    # A day is waived for everything; naming a chore as well is two different
    # instructions in one request.
    assert (
        api.post(
            "/api/waivers",
            json={
                "pin": PIN,
                "scope": "day",
                "day": start.isoformat(),
                "definition_id": 1,
            },
        ).status_code
        == 422
    )
    assert api.get("/api/waivers").json() == []


def test_a_closed_week_is_not_re_planned(api, scheme, week_dates):
    view = open_week(api)
    assert (
        api.post(
            f"/api/weeks/{view['week_id']}/void",
            json={"pin": PIN, "reason": "Half term"},
        ).status_code
        == 200
    )

    response = api.post(
        "/api/waivers",
        json={
            "pin": PIN,
            "scope": "chore_week",
            "week_id": view["week_id"],
            "definition_id": 1,
        },
    )
    assert response.status_code == 409
    assert "voided" in response.json()["detail"]


# --- 4. The savings acts the parent view needs ------------------------------


def test_a_withdrawal_lowers_the_balance_and_says_why(api, scheme, session):
    assert (
        api.post(
            "/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 1000}
        ).status_code
        == 201
    )

    response = api.post(
        "/api/savings/withdrawals",
        json={"pin": PIN, "amount_pence": 250, "reason": "Lego"},
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["amount_pence"] == -250
    assert entry["balance_after_pence"] == 750
    assert entry["reason"] == "Lego"

    assert api.get("/api/savings").json()["balance_pence"] == 750


def test_a_withdrawal_cannot_overdraw_or_go_unauthorised(api, scheme):
    api.post("/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 100})

    assert (
        api.post(
            "/api/savings/withdrawals",
            json={"pin": WRONG, "amount_pence": 50, "reason": "Sweets"},
        ).status_code
        == 401
    )
    assert (
        api.post(
            "/api/savings/withdrawals",
            json={"pin": PIN, "amount_pence": 500, "reason": "Too much"},
        ).status_code
        == 409
    )
    assert api.get("/api/savings").json()["balance_pence"] == 100


def test_reconciling_reports_the_difference_and_records_nothing(api, scheme):
    api.post("/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 1000})

    agreed = api.post("/api/savings/reconcile", json={"actual_balance_pence": 1000}).json()
    assert agreed["agrees"] is True
    assert agreed["difference_pence"] == 0
    assert agreed["put_right_by"] is None

    short = api.post("/api/savings/reconcile", json={"actual_balance_pence": 800}).json()
    assert short["agrees"] is False
    assert short["difference_pence"] == -200
    assert "withdrawal" in short["put_right_by"]

    over = api.post("/api/savings/reconcile", json={"actual_balance_pence": 1200}).json()
    assert over["difference_pence"] == 200
    assert "deciding" in over["put_right_by"]

    # Three reconciliations, and the ledger is exactly as it was.
    ledger = api.get("/api/savings").json()
    assert ledger["balance_pence"] == 1000
    assert len(ledger["entries"]) == 1


# --- 5. Settling, paying, and a week that is closed -------------------------


def test_a_week_settles_on_the_figure_that_was_read_and_then_is_closed(
    api, scheme, failing_week
):
    instance_id = failing_week["pending"]["instance_id"]
    review(api, [{"instance_id": instance_id, "decision": "confirm"}])

    proposal = api.get("/api/week").json()
    week_id = proposal["week_id"]
    total = proposal["totals"]["total_pence"]

    # Disagreeing with the figure is refused rather than quietly settled.
    assert (
        api.post(
            f"/api/weeks/{week_id}/settle",
            json={"pin": PIN, "agreed_total_pence": total + 1},
        ).status_code
        == 409
    )

    settled = api.post(
        f"/api/weeks/{week_id}/settle",
        json={"pin": PIN, "agreed_total_pence": total},
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["status"] == "settled"
    assert settled.json()["total_pence"] == total

    # Closed: the week view refuses it, and it cannot be settled twice.
    assert api.get(f"/api/week/{week_id}").status_code == 409
    assert (
        api.post(
            f"/api/weeks/{week_id}/settle",
            json={"pin": PIN, "agreed_total_pence": total},
        ).status_code
        == 409
    )

    # Owed until somebody hands it over.
    owed = api.get("/api/weeks/owed/outstanding").json()
    assert [item["week_id"] for item in owed] == [week_id]
    assert owed[0]["owed_pence"] == total


def test_paying_a_week_records_the_deposit_and_clears_the_debt(
    api, scheme, failing_week
):
    instance_id = failing_week["pending"]["instance_id"]
    review(api, [{"instance_id": instance_id, "decision": "confirm"}])
    week_id = api.get("/api/week").json()["week_id"]
    total = api.get(f"/api/weeks/{week_id}/proposal").json()["total_pence"]
    api.post(
        f"/api/weeks/{week_id}/settle", json={"pin": PIN, "agreed_total_pence": total}
    )

    payment = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week_id], "deposited_pence": 100},
    )
    assert payment.status_code == 200, payment.text
    assert payment.json()["paid_pence"] == total
    assert payment.json()["deposited_pence"] == 100
    assert payment.json()["kept_pence"] == total - 100
    assert payment.json()["savings_balance_pence"] == 100

    assert api.get("/api/weeks/owed/outstanding").json() == []
    assert api.get(f"/api/weeks/{week_id}").json()["paid_at"] is not None


def test_a_reward_is_recorded_with_its_reason(api, scheme, failing_week):
    response = api.post(
        "/api/rewards",
        json={"pin": PIN, "amount": "£2.50", "reason": "Helped with the shopping"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["amount_pence"] == 250
    assert response.json()["reason"] == "Helped with the shopping"

    # A parent-entered reward never touches the week's settled figures — a bad
    # week at the hoover does not make an award smaller — so it lands beside
    # them, and the payable total is the one that includes it.
    totals = api.get("/api/week").json()["totals"]
    assert totals["ad_hoc_reward_pence"] == 250
    assert totals["reward_pence"] == 0
    assert totals["payable_total_pence"] == totals["total_pence"] + 250

    preset = api.post("/api/rewards/presets/eagle_award", json={"pin": PIN})
    assert preset.status_code == 201
    assert preset.json()["reason"] == "Eagle award"
    assert api.get("/api/week").json()["totals"]["ad_hoc_reward_pence"] == 550


def test_a_voided_week_pays_nothing_and_is_closed(api, scheme, failing_week):
    week_id = api.get("/api/week").json()["week_id"]

    response = api.post(
        f"/api/weeks/{week_id}/void", json={"pin": PIN, "reason": "Chickenpox"}
    )
    assert response.status_code == 200, response.text
    week = response.json()
    assert week["status"] == "voided"
    assert week["total_pence"] == 0
    assert week["void_reason"] == "Chickenpox"

    # Nothing further can be done to it, including by the queue.
    assert api.get("/api/parent/queue").json() == []
    assert (
        api.post(
            "/api/parent/review/preview",
            json={
                "decisions": [
                    {
                        "instance_id": failing_week["pending"]["instance_id"],
                        "decision": "confirm",
                    }
                ]
            },
        ).status_code
        == 409
    )


def test_marking_an_instance_missed_is_a_parents_act(api, scheme, week_dates):
    start, _ = week_dates
    view = open_week(api)
    card = next(
        chore for chore in every_instance(view) if chore["due_date"] == start.isoformat()
    )

    assert (
        api.post(
            f"/api/instances/{card['instance_id']}/missed",
            json={"instance_id": card["instance_id"], "pin": WRONG},
        ).status_code
        == 401
    )

    response = api.post(
        f"/api/instances/{card['instance_id']}/missed",
        json={"instance_id": card["instance_id"], "pin": PIN, "note": "Not done"},
    )
    assert response.status_code == 200
    assert response.json()["miss_origin"] == "parent_marked"
    assert response.json()["authorised_by"] == "parent"

    # And now the child's screen has something to act on.
    assert api.get("/api/week").json()["recovery"]["outstanding"] == 1
