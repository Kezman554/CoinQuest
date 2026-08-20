"""Claiming, and a parent ruling on claims.

Every request here goes through the real app over HTTP. The point of this
session is that the API refuses things by itself, so testing the functions
directly would test the wrong thing entirely.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.models import (
    Cadence,
    Category,
    ChoreDefinition,
    ChoreInstance,
    InstanceState,
    Week,
    WeekStatus,
)

PIN = "0000"
WRONG = "9999"
SUNDAY = date(2026, 8, 16)
SATURDAY = date(2026, 8, 22)
NOW = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def api(session, monkeypatch):
    """The real app, talking to the migrated test database."""
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def week(session) -> Week:
    week = Week(start_date=SUNDAY, end_date=SATURDAY)
    session.add(week)
    session.commit()
    return week


@pytest.fixture()
def instances(session, week) -> list[ChoreInstance]:
    definition = ChoreDefinition(
        name="Make bed",
        cadence=Cadence.DAILY,
        category=Category.BASIC,
        amount_pence=50,
    )
    session.add(definition)
    session.commit()

    rows = [
        ChoreInstance(
            definition_id=definition.id,
            week_id=week.id,
            due_date=day,
        )
        for day in (SUNDAY, date(2026, 8, 17), date(2026, 8, 18))
    ]
    session.add_all(rows)
    session.commit()
    return rows


def claim(api, instance) -> None:
    assert api.post("/api/claims", json={"instance_id": instance.id}).status_code == 200


# --- 1. Claiming is unauthenticated and leaves the claim pending ------------


def test_claiming_needs_no_pin_and_marks_the_instance_pending(api, session, instances):
    response = api.post("/api/claims", json={"instance_id": instances[0].id})
    assert response.status_code == 200

    body = response.json()
    assert body["state"] == "claimed"
    assert body["claimed_at"] is not None
    assert body["confirmed_at"] is None
    # Pending means nobody has authorised anything yet.
    assert body["authorised_by"] is None

    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).state is InstanceState.CLAIMED


def test_a_claim_cannot_be_made_twice(api, instances):
    claim(api, instances[0])
    again = api.post("/api/claims", json={"instance_id": instances[0].id})
    assert again.status_code == 409


def test_claiming_something_that_does_not_exist_is_a_404(api):
    assert api.post("/api/claims", json={"instance_id": 999}).status_code == 404


def test_a_closed_week_refuses_a_claim(api, session, week, instances):
    week.status = WeekStatus.SETTLED
    week.settled_basic_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 0
    week.closed_at = NOW
    session.commit()

    response = api.post("/api/claims", json={"instance_id": instances[0].id})
    assert response.status_code == 409
    assert "settled" in response.json()["detail"]


# --- 3. A wrong PIN is refused, server-side ---------------------------------


def test_a_batch_with_the_wrong_pin_is_refused_outright(api, session, instances):
    for instance in instances:
        claim(api, instance)

    response = api.post(
        "/api/claims/review",
        json={
            "pin": WRONG,
            "decisions": [
                {"instance_id": instance.id, "decision": "confirm"}
                for instance in instances
            ],
        },
    )
    assert response.status_code == 401

    # And nothing moved. A refusal is not a partial application.
    session.expire_all()
    for instance in instances:
        assert session.get(ChoreInstance, instance.id).state is InstanceState.CLAIMED
        assert session.get(ChoreInstance, instance.id).confirmed_at is None


def test_a_batch_with_no_pin_at_all_is_refused(api, instances):
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={"decisions": [{"instance_id": instances[0].id, "decision": "confirm"}]},
    )
    assert response.status_code == 422  # the body is not even a valid request


def test_an_empty_pin_is_refused(api, instances):
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={
            "pin": "",
            "decisions": [{"instance_id": instances[0].id, "decision": "confirm"}],
        },
    )
    assert response.status_code == 401


def test_the_refusal_gives_nothing_away(api, instances):
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={
            "pin": WRONG,
            "decisions": [{"instance_id": instances[0].id, "decision": "confirm"}],
        },
    )
    assert response.json()["detail"] == "Not authorised."


def test_the_pin_is_never_returned_to_a_client(api, instances):
    # Not in a success, not in a refusal, not in a validation error.
    claim(api, instances[0])
    decisions = [{"instance_id": instances[0].id, "decision": "confirm"}]

    for pin in (PIN, WRONG):
        response = api.post(
            "/api/claims/review", json={"pin": pin, "decisions": decisions}
        )
        assert pin not in response.text

    malformed = api.post(
        "/api/claims/review",
        json={"pin": WRONG, "decisions": [{"instance_id": 1, "decision": "maybe"}]},
    )
    assert WRONG not in malformed.text


def test_the_pin_does_not_appear_in_the_public_schema(api):
    # The schema describes the field, but nothing anywhere carries its value.
    schema = api.get("/openapi.json").json()
    assert PIN not in api.get("/openapi.json").text
    assert "pin" in schema["components"]["schemas"]["ReviewRequest"]["properties"]


# --- 2 and 4. One batch, one authorisation, all or nothing ------------------


def test_a_valid_batch_confirms_and_rejects_together(api, session, instances):
    for instance in instances:
        claim(api, instance)

    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instances[0].id, "decision": "confirm"},
                {"instance_id": instances[1].id, "decision": "confirm"},
                {"instance_id": instances[2].id, "decision": "reject"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == [instances[0].id, instances[1].id]
    assert body["rejected"] == [instances[2].id]

    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).state is InstanceState.CONFIRMED
    assert session.get(ChoreInstance, instances[1].id).state is InstanceState.CONFIRMED
    # A rejected claim goes back to provisional, not to missed: the child can
    # still do it before the week closes.
    rejected = session.get(ChoreInstance, instances[2].id)
    assert rejected.state is InstanceState.UNTOUCHED
    assert rejected.claimed_at is None


def test_a_batch_containing_one_inapplicable_item_applies_none_of_it(
    api, session, instances
):
    claim(api, instances[0])
    claim(api, instances[1])
    # The third was never claimed, so there is nothing to rule on.

    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instances[0].id, "decision": "confirm"},
                {"instance_id": instances[1].id, "decision": "confirm"},
                {"instance_id": instances[2].id, "decision": "confirm"},
            ],
        },
    )
    assert response.status_code == 409
    assert "Nothing in this batch was applied" in response.json()["detail"]

    # The two that could have been applied were not.
    session.expire_all()
    for instance in instances[:2]:
        stored = session.get(ChoreInstance, instance.id)
        assert stored.state is InstanceState.CLAIMED
        assert stored.confirmed_at is None
        assert stored.authorised_by is None


def test_a_batch_naming_something_that_does_not_exist_applies_none_of_it(
    api, session, instances
):
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instances[0].id, "decision": "confirm"},
                {"instance_id": 999, "decision": "confirm"},
            ],
        },
    )
    assert response.status_code == 404

    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).state is InstanceState.CLAIMED


def test_a_batch_touching_a_closed_week_applies_none_of_it(
    api, session, week, instances
):
    for instance in instances:
        claim(api, instance)
    week.status = WeekStatus.VOIDED
    week.settled_basic_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 0
    week.closed_at = NOW
    session.commit()

    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instances[0].id, "decision": "confirm"}
            ],
        },
    )
    assert response.status_code == 409

    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).state is InstanceState.CLAIMED


def test_an_empty_batch_is_not_a_submission(api):
    response = api.post("/api/claims/review", json={"pin": PIN, "decisions": []})
    assert response.status_code == 422


def test_the_same_instance_cannot_be_ruled_on_twice_in_one_batch(api, instances):
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instances[0].id, "decision": "confirm"},
                {"instance_id": instances[0].id, "decision": "reject"},
            ],
        },
    )
    assert response.status_code == 422


# --- 5. Marking missed directly ---------------------------------------------


def test_a_parent_can_mark_an_instance_missed(api, session, instances):
    response = api.post(
        f"/api/instances/{instances[0].id}/missed",
        json={"pin": PIN, "instance_id": instances[0].id, "note": "Not done"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "missed"
    assert body["missed_at"] is not None
    assert body["authorised_by"] == "parent"


def test_marking_missed_needs_the_pin_too(api, session, instances):
    response = api.post(
        f"/api/instances/{instances[0].id}/missed",
        json={"pin": WRONG, "instance_id": instances[0].id},
    )
    assert response.status_code == 401

    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).state is InstanceState.UNTOUCHED


def test_a_claimed_instance_may_be_marked_missed(api, session, instances):
    claim(api, instances[0])
    response = api.post(
        f"/api/instances/{instances[0].id}/missed",
        json={"pin": PIN, "instance_id": instances[0].id},
    )
    assert response.status_code == 200
    assert response.json()["claimed_at"] is None


def test_confirmed_work_is_not_taken_back_by_marking_it_missed(
    api, session, instances
):
    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "confirm"}],
        },
    )
    response = api.post(
        f"/api/instances/{instances[0].id}/missed",
        json={"pin": PIN, "instance_id": instances[0].id},
    )
    assert response.status_code == 409

    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).state is InstanceState.CONFIRMED


def test_the_path_and_the_body_must_agree(api, instances):
    response = api.post(
        f"/api/instances/{instances[0].id}/missed",
        json={"pin": PIN, "instance_id": instances[1].id},
    )
    assert response.status_code == 400


# --- 6. The authorising party is recorded -----------------------------------


def test_every_confirmation_records_who_authorised_it(api, session, instances):
    for instance in instances:
        claim(api, instance)
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instance.id, "decision": "confirm"}
                for instance in instances
            ],
        },
    )

    session.expire_all()
    for instance in instances:
        stored = session.get(ChoreInstance, instance.id)
        assert stored.authorised_by == "parent"
        assert stored.confirmed_at is not None


def test_a_rejection_records_who_rejected_it(api, session, instances):
    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "reject"}],
        },
    )
    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).authorised_by == "parent"


def test_the_party_comes_from_the_pin_and_not_from_the_request(api, session, instances):
    # A client says what it wants done, never who it is. Anything it asserts
    # about its own identity is ignored.
    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "authorised_by": "someone else",
            "party": "someone else",
            "decisions": [{"instance_id": instances[0].id, "decision": "confirm"}],
        },
    )
    session.expire_all()
    assert session.get(ChoreInstance, instances[0].id).authorised_by == "parent"


def test_the_database_refuses_a_confirmation_with_no_author(session, instances):
    # Belt and braces: even if a future caller bypassed the router, a
    # confirmation that names nobody is not storable.
    from sqlalchemy.exc import IntegrityError

    instance = session.get(ChoreInstance, instances[0].id)
    instance.state = InstanceState.CONFIRMED
    instance.confirmed_at = NOW
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- A rejection leaves a trace --------------------------------------------


def test_a_rejection_is_recorded_even_though_the_state_goes_back(api, session, instances):
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "reject"}],
        },
    )
    assert response.status_code == 200

    session.expire_all()
    stored = session.get(ChoreInstance, instances[0].id)
    # The state is provisional again, so no rule has changed...
    assert stored.state is InstanceState.UNTOUCHED
    assert stored.claimed_at is None
    # ...but the week view can now say that a claim was made and refused.
    assert stored.rejected_at is not None
    assert stored.rejection_count == 1


def test_a_rejected_instance_is_distinguishable_from_an_untouched_one(api, instances):
    untouched = api.post("/api/claims", json={"instance_id": instances[1].id}).json()
    assert untouched["rejection_count"] == 0
    assert untouched["rejected_at"] is None

    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "reject"}],
        },
    )
    # Re-claiming shows the history, so the child is told rather than left to
    # wonder whether the first tap registered at all.
    reclaimed = api.post("/api/claims", json={"instance_id": instances[0].id}).json()
    assert reclaimed["state"] == "claimed"
    assert reclaimed["rejection_count"] == 1
    assert reclaimed["rejected_at"] is not None


def test_claiming_again_does_not_erase_the_rejection(api, session, instances):
    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "reject"}],
        },
    )
    session.expire_all()
    first_rejection = session.get(ChoreInstance, instances[0].id).rejected_at

    claim(api, instances[0])
    session.expire_all()
    stored = session.get(ChoreInstance, instances[0].id)
    assert stored.rejected_at == first_rejection
    assert stored.rejection_count == 1


def test_three_rejections_do_not_read_as_never_having_claimed(api, session, instances):
    for _ in range(3):
        claim(api, instances[0])
        api.post(
            "/api/claims/review",
            json={
                "pin": PIN,
                "decisions": [{"instance_id": instances[0].id, "decision": "reject"}],
            },
        )

    session.expire_all()
    stored = session.get(ChoreInstance, instances[0].id)
    assert stored.state is InstanceState.UNTOUCHED
    assert stored.rejection_count == 3


def test_a_confirmation_after_a_rejection_keeps_both_facts(api, session, instances):
    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "reject"}],
        },
    )
    claim(api, instances[0])
    api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [{"instance_id": instances[0].id, "decision": "confirm"}],
        },
    )

    session.expire_all()
    stored = session.get(ChoreInstance, instances[0].id)
    assert stored.state is InstanceState.CONFIRMED
    assert stored.confirmed_at is not None
    assert stored.rejection_count == 1  # it was refused once on the way here


def test_a_refused_batch_records_no_rejection(api, session, instances):
    # The all-or-nothing rule covers the new columns too.
    claim(api, instances[0])
    response = api.post(
        "/api/claims/review",
        json={
            "pin": PIN,
            "decisions": [
                {"instance_id": instances[0].id, "decision": "reject"},
                {"instance_id": instances[2].id, "decision": "reject"},  # never claimed
            ],
        },
    )
    assert response.status_code == 409

    session.expire_all()
    stored = session.get(ChoreInstance, instances[0].id)
    assert stored.rejection_count == 0
    assert stored.rejected_at is None


def test_a_rejection_count_without_a_time_is_not_storable(session, instances):
    from sqlalchemy.exc import IntegrityError

    instance = session.get(ChoreInstance, instances[0].id)
    instance.rejection_count = 1  # but no rejected_at
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
