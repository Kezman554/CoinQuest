"""Settling on an assignment a parent chose instead of the computed one.

The scheme proposes and a parent agrees. Sometimes they agree to something
worse than the app worked out, because a passed week can be worth more to a
child than the fifty pence it cost. That is theirs to decide. The rules are
not.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

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
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def scheme(session):
    """350p of basics, and three bonus chores at 100p, 300p and 200p."""
    definitions = {
        "beds": ChoreDefinition(
            name="Make bed",
            cadence=Cadence.DAILY,
            category=Category.BASIC,
            amount_pence=350,
        ),
        "hoover": ChoreDefinition(
            name="Hoover",
            cadence=Cadence.WEEKLY_COUNT,
            category=Category.BONUS,
            amount_pence=100,
            times_per_week=2,
        ),
        "shed": ChoreDefinition(
            name="Clear the shed",
            cadence=Cadence.ONE_OFF,
            category=Category.BONUS,
            amount_pence=300,
        ),
        "bins": ChoreDefinition(
            name="Bins",
            cadence=Cadence.WEEKLY_COUNT,
            category=Category.BONUS,
            amount_pence=200,
            times_per_week=1,
        ),
        "tidy": ChoreDefinition(
            name="Tidy all week",
            cadence=Cadence.WEEKLY_CONDITION,
            category=Category.BONUS,
            amount_pence=500,
        ),
    }
    session.add_all(definitions.values())
    session.commit()
    return definitions


@pytest.fixture()
def week(session) -> Week:
    week = Week(start_date=SUNDAY, end_date=SATURDAY)
    session.add(week)
    session.commit()
    return week


def add(session, week, definition, *, confirmed=0, untouched=0):
    rows = []
    for index in range(confirmed + untouched):
        done = index < confirmed
        rows.append(
            ChoreInstance(
                definition_id=definition.id,
                week_id=week.id,
                due_date=(
                    date.fromordinal(SUNDAY.toordinal() + index)
                    if definition.cadence is Cadence.DAILY
                    else None
                ),
                sequence=1 if definition.cadence is Cadence.DAILY else index + 1,
                state=InstanceState.CONFIRMED if done else InstanceState.UNTOUCHED,
                confirmed_at=week.created_at if done else None,
                authorised_by="parent" if done else None,
            )
        )
    session.add_all(rows)
    session.commit()
    return rows


@pytest.fixture()
def losing_week(session, week, scheme):
    """Two misses, and only expensive bonuses to cover them with.

    Recovering both costs 400p of bonus chores to rescue 350p of chore pay, so
    the optimiser declines it and proposes 500p: the base, no chore pay, and
    both bonuses paid.
    """
    add(session, week, scheme["beds"], confirmed=5, untouched=2)
    add(session, week, scheme["hoover"], confirmed=2)
    add(session, week, scheme["shed"], confirmed=1)
    return week


def override(*pairs, reason=None):
    return {
        "recoveries": [
            {"spend_definition_id": spend, "for_definition_id": missed}
            for spend, missed in pairs
        ],
        "reason": reason,
    }


# --- The computed proposal, for contrast ------------------------------------


def test_the_optimiser_declines_a_recovery_that_loses_money(api, losing_week, scheme):
    body = api.get(f"/api/weeks/{losing_week.id}/proposal").json()
    assert body["misses"] == 2
    assert body["misses_outstanding"] == 2
    assert body["chore_pay_pence"] == 0
    assert body["bonus_pence"] == 400          # both kept and paid
    assert body["total_pence"] == 500          # 100 base + 400 bonuses
    assert body["overridden"] is False
    assert body["foregone_pence"] == 0


# --- 1. A supplied assignment is accepted, even when it loses money ---------


def test_an_override_that_loses_money_is_proposed(api, losing_week, scheme):
    # The parent decides the passed week is worth more than the fifty pence.
    body = api.post(
        f"/api/weeks/{losing_week.id}/proposal",
        json={
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id),
                (scheme["shed"].id, scheme["beds"].id),
            )
        },
    ).json()

    assert body["overridden"] is True
    assert body["misses_outstanding"] == 0
    assert body["chore_pay_pence"] == 350      # rescued
    assert body["bonus_pence"] == 0            # both spent to do it
    assert body["total_pence"] == 450          # 100 base + 350
    assert body["optimum_total_pence"] == 500  # what the app would have paid
    assert body["foregone_pence"] == 50        # and what the choice cost


def test_an_override_that_loses_money_settles_at_the_lower_figure(
    api, session, losing_week, scheme
):
    api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 450,
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id),
                (scheme["shed"].id, scheme["beds"].id),
                reason="He had a hard week and the chore pay matters to him",
            ),
        },
    )

    session.expire_all()
    stored = session.get(Week, losing_week.id)
    assert stored.status is WeekStatus.SETTLED
    assert stored.settled_total_pence == 450   # less than the app offered
    assert stored.settled_chore_pay_pence == 350
    assert stored.settled_bonus_pence == 0


def test_an_override_may_choose_to_recover_nothing(api, losing_week, scheme):
    # An empty list is an instruction, not an absence of one.
    body = api.post(
        f"/api/weeks/{losing_week.id}/proposal", json={"override": override()}
    ).json()
    assert body["overridden"] is True
    assert body["chore_pay_pence"] == 0
    assert body["total_pence"] == 500


def test_an_override_may_spend_one_of_two(api, losing_week, scheme):
    # One miss covered, one left: the chore pay still fails, and 300p is kept
    # for nothing. Allowed, because a parent may be wrong about arithmetic.
    body = api.post(
        f"/api/weeks/{losing_week.id}/proposal",
        json={"override": override((scheme["hoover"].id, scheme["beds"].id))},
    ).json()
    assert body["misses_outstanding"] == 1
    assert body["chore_pay_pence"] == 0
    assert body["bonus_pence"] == 300
    assert body["total_pence"] == 400
    assert body["foregone_pence"] == 100


# --- 2. Validated, not trusted ----------------------------------------------


def refuse(api, week, supplied) -> str:
    response = api.post(f"/api/weeks/{week.id}/proposal", json={"override": supplied})
    assert response.status_code == 422, response.text
    return response.json()["detail"]


def test_an_override_beyond_the_cap_is_refused(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=4, untouched=3)   # three misses
    add(session, week, scheme["hoover"], confirmed=2)
    add(session, week, scheme["shed"], confirmed=1)
    add(session, week, scheme["bins"], confirmed=1)

    detail = refuse(
        api,
        week,
        override(
            (scheme["hoover"].id, scheme["beds"].id),
            (scheme["shed"].id, scheme["beds"].id),
            (scheme["bins"].id, scheme["beds"].id),
        ),
    )
    assert "At most 2 misses" in detail


def test_spending_a_bonus_chore_that_was_never_completed_is_refused(
    api, session, week, scheme
):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)
    add(session, week, scheme["hoover"], confirmed=1, untouched=1)  # 1 of 2 done

    detail = refuse(api, week, override((scheme["hoover"].id, scheme["beds"].id)))
    assert "was not completed this week" in detail


def test_spending_a_bonus_chore_with_no_instances_at_all_is_refused(
    api, session, week, scheme
):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)

    detail = refuse(api, week, override((scheme["bins"].id, scheme["beds"].id)))
    assert "was not completed this week" in detail


def test_recovering_a_miss_that_does_not_exist_is_refused(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=7)      # nothing missed
    add(session, week, scheme["hoover"], confirmed=2)

    detail = refuse(api, week, override((scheme["hoover"].id, scheme["beds"].id)))
    assert "was not missed this week" in detail


def test_recovering_more_misses_than_happened_is_refused(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)   # one miss
    add(session, week, scheme["hoover"], confirmed=2)
    add(session, week, scheme["shed"], confirmed=1)

    detail = refuse(
        api,
        week,
        override(
            (scheme["hoover"].id, scheme["beds"].id),
            (scheme["shed"].id, scheme["beds"].id),
        ),
    )
    assert "was missed once this week" in detail
    assert "2 misses cannot be recovered" in detail


def test_spending_the_same_chore_twice_is_refused(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=5, untouched=2)
    add(session, week, scheme["hoover"], confirmed=2)

    detail = refuse(
        api,
        week,
        override(
            (scheme["hoover"].id, scheme["beds"].id),
            (scheme["hoover"].id, scheme["beds"].id),
        ),
    )
    assert "spent twice" in detail


def test_spending_a_basic_chore_is_refused(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)

    detail = refuse(api, week, override((scheme["beds"].id, scheme["beds"].id)))
    assert "not a bonus chore" in detail


def test_spending_a_chore_that_cannot_be_done_on_demand_is_refused(
    api, session, week, scheme
):
    # A week-long condition is completed and paid, but by the time you know
    # about the miss it is already decided. Session F's rule, and a parent
    # does not get to set it aside.
    add(session, week, scheme["beds"], confirmed=6, untouched=1)
    add(session, week, scheme["tidy"], confirmed=1)

    detail = refuse(api, week, override((scheme["tidy"].id, scheme["beds"].id)))
    assert "cannot be completed on demand" in detail


def test_spending_a_chore_that_does_not_exist_is_refused(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)
    detail = refuse(api, week, override((9999, scheme["beds"].id)))
    assert "no chore 9999" in detail


def test_a_refused_override_changes_nothing(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)
    refuse(api, week, override((scheme["bins"].id, scheme["beds"].id)))

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.OPEN
    states = [instance.state for instance in session.get(Week, week.id).instances]
    assert states.count(InstanceState.UNTOUCHED) == 1  # not turned into a miss


def test_settling_with_an_unlawful_override_is_refused(api, session, losing_week, scheme):
    response = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 450,
            "override": override((scheme["bins"].id, scheme["beds"].id)),
        },
    )
    assert response.status_code == 422

    session.expire_all()
    assert session.get(Week, losing_week.id).status is WeekStatus.OPEN


# --- 3. The override is recorded --------------------------------------------


def settle_overridden(api, week, scheme, reason="He earned the week"):
    return api.post(
        f"/api/weeks/{week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 450,
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id),
                (scheme["shed"].id, scheme["beds"].id),
                reason=reason,
            ),
        },
    )


def test_a_settled_week_records_that_it_was_overridden(api, session, losing_week, scheme):
    assert settle_overridden(api, losing_week, scheme).status_code == 200

    session.expire_all()
    stored = session.get(Week, losing_week.id)
    assert stored.overridden_by == "parent"
    assert stored.override_reason == "He earned the week"
    # The figure that was turned down, kept beside the one that was paid: the
    # difference is the story, and neither number means much alone.
    assert stored.optimum_total_pence == 500
    assert stored.settled_total_pence == 450


def test_the_week_reads_back_as_overridden(api, losing_week, scheme):
    settle_overridden(api, losing_week, scheme)

    body = api.get(f"/api/weeks/{losing_week.id}").json()
    assert body["overridden_by"] == "parent"
    assert body["optimum_total_pence"] == 500
    assert body["total_pence"] == 450
    assert body["override_reason"] == "He earned the week"


def test_an_ordinary_settlement_records_no_override(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=7)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    session.expire_all()
    stored = session.get(Week, week.id)
    assert stored.overridden_by is None
    assert stored.override_reason is None
    assert stored.optimum_total_pence is None


def test_an_override_still_needs_the_pin(api, session, losing_week, scheme):
    response = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": WRONG,
            "agreed_total_pence": 450,
            "override": override((scheme["hoover"].id, scheme["beds"].id)),
        },
    )
    assert response.status_code == 401

    session.expire_all()
    assert session.get(Week, losing_week.id).status is WeekStatus.OPEN


# --- 4. The agreed figure is still checked ----------------------------------


def test_agreeing_the_computed_figure_for_an_overridden_week_is_refused(
    api, session, losing_week, scheme
):
    # The parent submits 500 — what the app proposed — alongside an override
    # worth 450. They have not read what they are agreeing to.
    response = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 500,
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id),
                (scheme["shed"].id, scheme["beds"].id),
                reason="He earned the week",
            ),
        },
    )
    assert response.status_code == 409
    assert "now proposes 450p, not 500p" in response.json()["detail"]

    session.expire_all()
    assert session.get(Week, losing_week.id).status is WeekStatus.OPEN


def test_agreeing_the_overridden_figure_without_the_override_is_refused(
    api, session, losing_week, scheme
):
    # And the other way round: 450 is not what this week proposes on its own.
    response = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": 450},
    )
    assert response.status_code == 409
    assert "now proposes 500p, not 450p" in response.json()["detail"]


# --- A settled overridden week is as closed as any other --------------------


def test_an_overridden_week_cannot_be_recomputed(api, session, losing_week, scheme):
    settle_overridden(api, losing_week, scheme)

    refusal = api.get(f"/api/weeks/{losing_week.id}/proposal")
    assert refusal.status_code == 409
    assert "never recomputed" in refusal.json()["detail"]

    # Nor through the override door, which is the one this session opened.
    second = api.post(
        f"/api/weeks/{losing_week.id}/proposal",
        json={"override": override((scheme["hoover"].id, scheme["beds"].id))},
    )
    assert second.status_code == 409

    from app.config import get_settings
    from app.services.settlement import NotOpen, propose

    with pytest.raises(NotOpen):
        propose(session, session.get(Week, losing_week.id), get_settings().tzinfo)


def test_an_overridden_week_cannot_be_settled_again(api, losing_week, scheme):
    settle_overridden(api, losing_week, scheme)
    assert settle_overridden(api, losing_week, scheme).status_code == 409


def test_an_overridden_weeks_figures_are_frozen(api, session, losing_week, scheme):
    from sqlalchemy.exc import IntegrityError, OperationalError

    settle_overridden(api, losing_week, scheme)

    for column, value in (
        ("settled_total_pence", 500),
        ("overridden_by", "'somebody else'"),
        ("optimum_total_pence", 450),
        ("override_reason", "'a different story'"),
    ):
        with pytest.raises((IntegrityError, OperationalError), match="closed forever"):
            session.execute(
                text(f"UPDATE weeks SET {column} = {value} WHERE id = :id"),
                {"id": losing_week.id},
            )
        session.rollback()


def test_an_overridden_week_survives_the_scheme_changing(
    api, session, losing_week, scheme
):
    settle_overridden(api, losing_week, scheme)

    scheme["beds"].amount_pence = 9000
    scheme["hoover"].amount_pence = 1
    scheme["shed"].is_available = False
    session.commit()

    body = api.get(f"/api/weeks/{losing_week.id}").json()
    assert body["total_pence"] == 450
    assert body["optimum_total_pence"] == 500
    assert body["chore_pay_pence"] == 350


# --- The wording, which a parent reads on a kitchen wall --------------------


def test_the_refusals_are_written_for_a_person(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=6, untouched=1)   # missed once
    add(session, week, scheme["hoover"], confirmed=2)
    add(session, week, scheme["shed"], confirmed=1)

    detail = refuse(
        api,
        week,
        override(
            (scheme["hoover"].id, scheme["beds"].id),
            (scheme["shed"].id, scheme["beds"].id),
        ),
    )
    assert "missed once this week" in detail
    assert "1 times" not in detail
    assert "2 misses cannot be recovered" in detail


def test_a_miss_that_never_happened_is_said_plainly(api, session, week, scheme):
    add(session, week, scheme["beds"], confirmed=7)
    add(session, week, scheme["hoover"], confirmed=2)

    detail = refuse(api, week, override((scheme["hoover"].id, scheme["beds"].id)))
    assert detail.endswith("was not missed this week, so there is nothing there to recover.")
    assert "0 times" not in detail


# --- An override that costs money has to say why ----------------------------


def test_an_override_that_loses_money_without_a_reason_is_refused(
    api, session, losing_week, scheme
):
    response = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 450,
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id),
                (scheme["shed"].id, scheme["beds"].id),
            ),
        },
    )
    assert response.status_code == 422
    assert "50p less than the 500p" in response.json()["detail"]
    assert "Say why" in response.json()["detail"]

    session.expire_all()
    assert session.get(Week, losing_week.id).status is WeekStatus.OPEN


def test_a_blank_reason_is_no_reason(api, session, losing_week, scheme):
    response = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 450,
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id),
                (scheme["shed"].id, scheme["beds"].id),
                reason="   ",
            ),
        },
    )
    assert response.status_code == 422


def test_an_override_that_costs_nothing_needs_no_reason(api, session, week, scheme):
    # Recovering one miss with the cheap chore is what the app would have done
    # anyway, so there is no difference to explain.
    add(session, week, scheme["beds"], confirmed=6, untouched=1)
    add(session, week, scheme["hoover"], confirmed=2)

    response = api.post(
        f"/api/weeks/{week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 450,
            "override": override((scheme["hoover"].id, scheme["beds"].id)),
        },
    )
    assert response.status_code == 200

    session.expire_all()
    stored = session.get(Week, week.id)
    assert stored.overridden_by == "parent"
    assert stored.override_reason is None
    assert stored.settled_total_pence == stored.optimum_total_pence


def test_the_database_refuses_a_costly_override_with_no_reason(session, week):
    from sqlalchemy.exc import IntegrityError

    # Belt and braces: the rule holds even if a future caller goes around the
    # service that enforces it.
    week.status = WeekStatus.SETTLED
    week.settled_base_pence = 100
    week.settled_chore_pay_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 100
    week.closed_at = NOW
    week.overridden_by = "parent"
    week.optimum_total_pence = 500   # 400p given up, and nothing said about it
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- A void takes no assignment ---------------------------------------------


def test_voiding_with_an_override_is_refused(api, session, losing_week, scheme):
    # A void zeroes the base, the chore pay and the bonuses, so there is
    # nothing for a make-good to rescue. Accepting one would record a
    # deliberate choice that changed nothing.
    response = api.post(
        f"/api/weeks/{losing_week.id}/void",
        json={
            "pin": PIN,
            "reason": "Grounded",
            "override": override((scheme["hoover"].id, scheme["beds"].id)),
        },
    )
    assert response.status_code == 422
    assert "nothing for a make-good to rescue" in response.text

    session.expire_all()
    assert session.get(Week, losing_week.id).status is WeekStatus.OPEN


def test_an_override_cannot_be_applied_to_an_already_voided_week(
    api, session, losing_week, scheme
):
    api.post(f"/api/weeks/{losing_week.id}/void", json={"pin": PIN, "reason": "Grounded"})

    preview = api.post(
        f"/api/weeks/{losing_week.id}/proposal",
        json={"override": override((scheme["hoover"].id, scheme["beds"].id))},
    )
    assert preview.status_code == 409
    assert "voided" in preview.json()["detail"]

    settle = api.post(
        f"/api/weeks/{losing_week.id}/settle",
        json={
            "pin": PIN,
            "agreed_total_pence": 100,
            "override": override(
                (scheme["hoover"].id, scheme["beds"].id), reason="Trying anyway"
            ),
        },
    )
    assert settle.status_code == 409

    session.expire_all()
    stored = session.get(Week, losing_week.id)
    assert stored.status is WeekStatus.VOIDED
    assert stored.overridden_by is None
