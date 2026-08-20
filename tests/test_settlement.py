"""Proposing a week's figures, and closing it on them.

The test that matters most is the last group: a settled week is read from its
own columns, and no amount of editing the scheme afterwards changes what it
says. That is asserted rather than assumed, in several directions.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.models import (
    Cadence,
    Category,
    ChoreDefinition,
    ChoreInstance,
    EarningEntry,
    EarningType,
    InstanceState,
    MissOrigin,
    SettlementLine,
    Week,
    WeekStatus,
)

PIN = "0000"
WRONG = "9999"
FIRST_SUNDAY = date(2026, 8, 16)
FIRST_SATURDAY = date(2026, 8, 22)
SECOND_SUNDAY = date(2026, 8, 23)
SECOND_SATURDAY = date(2026, 8, 29)


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
    """A small scheme: 350p of basics, a 100p bonus and a 250p reward."""
    beds = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=350
    )
    hoover = ChoreDefinition(
        name="Hoover",
        cadence=Cadence.WEEKLY_COUNT,
        category=Category.BONUS,
        amount_pence=100,
        times_per_week=2,
    )
    award = ChoreDefinition(
        name="School award",
        cadence=Cadence.EVENT,
        category=Category.REWARD,
        amount_pence=250,
    )
    session.add_all([beds, hoover, award])
    session.commit()
    return {"beds": beds, "hoover": hoover, "award": award}


def make_week(session, start=FIRST_SUNDAY, end=FIRST_SATURDAY) -> Week:
    week = Week(start_date=start, end_date=end)
    session.add(week)
    session.commit()
    return week


def add_instances(session, week, definition, *, confirmed=0, untouched=0, due=None):
    days = list(week.start_date.toordinal() + offset for offset in range(7))
    rows = []
    for index in range(confirmed + untouched):
        state = (
            InstanceState.CONFIRMED if index < confirmed else InstanceState.UNTOUCHED
        )
        rows.append(
            ChoreInstance(
                definition_id=definition.id,
                week_id=week.id,
                due_date=(
                    date.fromordinal(days[index])
                    if definition.cadence is Cadence.DAILY
                    else due
                ),
                sequence=1 if definition.cadence is Cadence.DAILY else index + 1,
                state=state,
                confirmed_at=week.created_at if state is InstanceState.CONFIRMED else None,
                authorised_by="parent" if state is InstanceState.CONFIRMED else None,
            )
        )
    session.add_all(rows)
    session.commit()
    return rows


def a_perfect_week(session, scheme, week):
    add_instances(session, week, scheme["beds"], confirmed=7)
    add_instances(session, week, scheme["hoover"], confirmed=2)


# --- 1. Proposing applies nothing -------------------------------------------


def test_a_proposal_breaks_the_week_down(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    add_instances(session, week, scheme["award"], confirmed=1)

    body = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert body["base_pence"] == 350
    assert body["chore_pay_pence"] == 350
    assert body["chore_pay_awarded"] is True
    assert body["bonus_pence"] == 100
    assert body["reward_pence"] == 250
    assert body["total_pence"] == 700
    assert body["misses"] == 0
    assert body["status"] == "open"


def test_a_proposal_changes_nothing_at_all(api, session, scheme):
    week = make_week(session)
    add_instances(session, week, scheme["beds"], confirmed=5, untouched=2)

    before = _snapshot(session)
    for _ in range(3):
        assert api.get(f"/api/weeks/{week.id}/proposal").status_code == 200
    assert _snapshot(session) == before

    # In particular, the untouched instances are still untouched. They become
    # misses at settlement and not before.
    session.expire_all()
    states = [instance.state for instance in session.get(Week, week.id).instances]
    assert states.count(InstanceState.UNTOUCHED) == 2
    assert states.count(InstanceState.MISSED) == 0


def _snapshot(session):
    rows = session.execute(
        text(
            "SELECT id, state, missed_at, miss_origin FROM chore_instances ORDER BY id"
        )
    ).all()
    weeks = session.execute(
        text("SELECT id, status, settled_total_pence, closed_at FROM weeks ORDER BY id")
    ).all()
    ledger = session.execute(text("SELECT count(*) FROM earnings_ledger")).scalar()
    lines = session.execute(text("SELECT count(*) FROM settlement_lines")).scalar()
    return rows, weeks, ledger, lines


def test_a_proposal_needs_no_pin(api, session, scheme):
    # The child is meant to see where he stands without asking anybody.
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    assert api.get(f"/api/weeks/{week.id}/proposal").status_code == 200


def test_a_proposal_shows_the_recovery_it_would_apply(api, session, scheme):
    week = make_week(session)
    add_instances(session, week, scheme["beds"], confirmed=6, untouched=1)
    add_instances(session, week, scheme["hoover"], confirmed=2)

    body = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert body["misses"] == 1
    assert body["misses_outstanding"] == 0
    assert body["recoveries"] == [
        {"miss_name": "Make bed", "spent_name": "Hoover", "forgone_pence": 100}
    ]
    assert body["chore_pay_pence"] == 350
    assert body["bonus_pence"] == 0      # spent, not paid
    assert body["total_pence"] == 350


def test_a_proposal_shows_a_week_that_cannot_be_recovered(api, session, scheme):
    week = make_week(session)
    add_instances(session, week, scheme["beds"], confirmed=3, untouched=4)
    add_instances(session, week, scheme["hoover"], confirmed=2)

    body = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert body["misses"] == 4
    assert body["misses_outstanding"] == 4   # past the cap of two
    assert body["chore_pay_awarded"] is False
    assert body["chore_pay_pence"] == 0
    assert body["bonus_pence"] == 100        # kept, since spending it is futile
    assert body["total_pence"] == 100


# --- 2. Settling needs explicit agreement, authorised ------------------------


def test_settling_without_the_pin_is_refused(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)

    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": WRONG, "agreed_total_pence": 450}
    )
    assert response.status_code == 401

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.OPEN
    assert session.get(Week, week.id).settled_total_pence is None


def test_settling_writes_the_agreed_figures_into_the_week(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    assert proposal["total_pence"] == 450

    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "settled"
    assert body["total_pence"] == 450
    assert body["chore_pay_pence"] == 350
    assert body["bonus_pence"] == 100

    session.expire_all()
    stored = session.get(Week, week.id)
    assert stored.status is WeekStatus.SETTLED
    assert stored.settled_total_pence == 450
    assert stored.closed_at is not None


def test_settling_on_a_figure_the_week_no_longer_proposes_is_refused(
    api, session, scheme
):
    # The parent read 450p, then a claim was confirmed before they agreed.
    week = make_week(session)
    a_perfect_week(session, scheme, week)

    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 9999}
    )
    assert response.status_code == 409
    assert "Read the figures again" in response.json()["detail"]

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.OPEN


def test_settling_records_the_misses_it_settled_on(api, session, scheme):
    week = make_week(session)
    add_instances(session, week, scheme["beds"], confirmed=5, untouched=2)

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    api.post(
        f"/api/weeks/{week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": proposal["total_pence"]},
    )

    session.expire_all()
    missed = [
        instance
        for instance in session.get(Week, week.id).instances
        if instance.state is InstanceState.MISSED
    ]
    assert len(missed) == 2
    for instance in missed:
        assert instance.miss_origin is MissOrigin.INFERRED_AT_SETTLEMENT
        assert instance.authorised_by is None  # nobody decided an absence


def test_settling_writes_one_earnings_entry(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    entries = session.query(EarningEntry).all()
    assert len(entries) == 1
    assert entries[0].entry_type is EarningType.WEEK_SETTLEMENT
    assert entries[0].amount_pence == 450


def test_a_week_cannot_be_settled_twice(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    again = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert again.status_code == 409


# --- 3. Several open weeks at once ------------------------------------------


def test_two_weeks_are_open_at_once_and_settle_on_their_own_figures(
    api, session, scheme
):
    first = make_week(session)
    second = make_week(session, SECOND_SUNDAY, SECOND_SATURDAY)

    a_perfect_week(session, scheme, first)                       # 450p
    add_instances(session, second, scheme["beds"], confirmed=7)  # 350p, no bonus

    assert api.get(f"/api/weeks/{first.id}/proposal").json()["total_pence"] == 450
    assert api.get(f"/api/weeks/{second.id}/proposal").json()["total_pence"] == 350

    # Settling the second leaves the first exactly as it was.
    api.post(f"/api/weeks/{second.id}/settle", json={"pin": PIN, "agreed_total_pence": 350})

    session.expire_all()
    assert session.get(Week, second.id).status is WeekStatus.SETTLED
    assert session.get(Week, second.id).settled_total_pence == 350
    assert session.get(Week, first.id).status is WeekStatus.OPEN
    assert api.get(f"/api/weeks/{first.id}/proposal").json()["total_pence"] == 450


def test_the_week_list_shows_which_are_open(api, session, scheme):
    first = make_week(session)
    second = make_week(session, SECOND_SUNDAY, SECOND_SATURDAY)
    a_perfect_week(session, scheme, first)
    api.post(f"/api/weeks/{first.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    listed = api.get("/api/weeks").json()
    assert [week["status"] for week in listed] == ["settled", "open"]
    assert listed[0]["total_pence"] == 450
    assert listed[1]["total_pence"] is None
    assert listed[1]["week_id"] == second.id


# --- 4. Open weeks stay editable; closed ones do not ------------------------


def test_an_open_week_is_still_claimable(api, session, scheme):
    week = make_week(session)
    rows = add_instances(session, week, scheme["beds"], untouched=7)
    assert api.post("/api/claims", json={"instance_id": rows[0].id}).status_code == 200


def test_a_settled_week_refuses_a_claim(api, session, scheme):
    week = make_week(session)
    add_instances(session, week, scheme["beds"], confirmed=6)
    rows = add_instances(session, week, scheme["hoover"], untouched=1)

    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    api.post(
        f"/api/weeks/{week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": proposal["total_pence"]},
    )

    response = api.post("/api/claims", json={"instance_id": rows[0].id})
    assert response.status_code == 409


def test_a_settled_weeks_figures_cannot_be_updated_even_directly(api, session, scheme):
    from sqlalchemy.exc import IntegrityError, OperationalError

    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    with pytest.raises((IntegrityError, OperationalError), match="closed forever"):
        session.execute(
            text("UPDATE weeks SET settled_total_pence = 1 WHERE id = :id"),
            {"id": week.id},
        )
    session.rollback()


# --- 5. Voiding -------------------------------------------------------------


def test_voiding_pays_nothing_and_keeps_the_record(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)

    response = api.post(
        f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": "Away all week"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "voided"
    assert body["total_pence"] == 0
    assert body["void_reason"] == "Away all week"

    session.expire_all()
    stored = session.get(Week, week.id)
    assert stored.settled_total_pence == 0
    # Every instance survives: voiding is a statement about the money, not
    # about the work.
    assert len(stored.instances) == 9
    assert all(
        instance.state is InstanceState.CONFIRMED for instance in stored.instances
    )


def test_voiding_leaves_rewards_already_earned_intact(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    add_instances(session, week, scheme["award"], confirmed=1)

    api.post(f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": "Away"})

    # The week pays nothing...
    session.expire_all()
    assert session.get(Week, week.id).settled_total_pence == 0

    # ...and the reward, which was earned by something happening rather than
    # by the week going well, is still his.
    rewards = (
        session.query(EarningEntry)
        .filter(EarningEntry.entry_type == EarningType.REWARD)
        .all()
    )
    assert len(rewards) == 1
    assert rewards[0].amount_pence == 250
    assert "School award" in rewards[0].reason


def test_voiding_needs_the_pin_and_a_reason(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)

    assert (
        api.post(
            f"/api/weeks/{week.id}/void", json={"pin": WRONG, "reason": "Away"}
        ).status_code
        == 401
    )
    assert (
        api.post(f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": ""}).status_code
        == 422
    )

    session.expire_all()
    assert session.get(Week, week.id).status is WeekStatus.OPEN


def test_a_voided_week_cannot_be_settled_afterwards(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/void", json={"pin": PIN, "reason": "Away"})

    response = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert response.status_code == 409


# --- The rule this session exists for ---------------------------------------


def test_changing_a_chores_amount_leaves_the_settled_figures_unchanged(
    api, session, scheme
):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    # The scheme is reviewed. Everything about both chores changes.
    scheme["beds"].amount_pence = 900
    scheme["beds"].name = "Make bed properly"
    scheme["hoover"].amount_pence = 5
    scheme["hoover"].is_available = False
    session.commit()

    body = api.get(f"/api/weeks/{week.id}").json()
    assert body["total_pence"] == 450        # not 905
    assert body["chore_pay_pence"] == 350    # not 900
    assert body["bonus_pence"] == 100        # not 5

    # And the lines still read as they did that week.
    named = {line["chore_name"]: line for line in body["lines"]}
    assert named["Make bed"]["amount_pence"] == 350
    assert named["Hoover"]["unit_amount_pence"] == 100
    assert "Make bed properly" not in named


def test_no_path_recomputes_a_settled_week(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    scheme["beds"].amount_pence = 900
    session.commit()

    # The proposal endpoint refuses outright rather than answering with a
    # figure computed from today's chores.
    refusal = api.get(f"/api/weeks/{week.id}/proposal")
    assert refusal.status_code == 409
    assert "never recomputed" in refusal.json()["detail"]

    # The service function refuses too, so no future caller can go around it.
    from app.config import get_settings
    from app.services.settlement import NotOpen, propose

    with pytest.raises(NotOpen):
        propose(session, session.get(Week, week.id), get_settings().tzinfo)

    # And the week reads the same as it did.
    assert api.get(f"/api/weeks/{week.id}").json()["total_pence"] == 450


def test_a_settled_week_survives_its_chores_being_deleted(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    # Instances hold the definitions in place, so clear the week out first —
    # the point is that the settled figures do not depend on any of it.
    session.execute(text("DELETE FROM chore_instances WHERE week_id = :id"), {"id": week.id})
    session.execute(text("DELETE FROM chore_definitions"))
    session.commit()
    session.expire_all()

    body = api.get(f"/api/weeks/{week.id}").json()
    assert body["total_pence"] == 450
    named = {line["chore_name"]: line for line in body["lines"]}
    assert named["Make bed"]["amount_pence"] == 350

    lines = session.query(SettlementLine).all()
    assert all(line.source_definition_id is None for line in lines)  # provenance gone
    assert sum(line.amount_pence for line in lines) == 450           # money intact


def test_the_settled_figures_come_from_the_weeks_own_columns(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    api.post(f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450})

    session.expire_all()
    from app.services.settlement import stored_figures

    figures = stored_figures(session.get(Week, week.id))
    assert figures["total_pence"] == 450
    assert figures["chore_pay_pence"] == 350
    assert figures["bonus_pence"] == 100
    assert figures["status"] == "settled"


def test_every_stored_amount_is_an_integer_number_of_pence(api, session, scheme):
    week = make_week(session)
    a_perfect_week(session, scheme, week)
    add_instances(session, week, scheme["award"], confirmed=1)
    proposal = api.get(f"/api/weeks/{week.id}/proposal").json()
    api.post(
        f"/api/weeks/{week.id}/settle",
        json={"pin": PIN, "agreed_total_pence": proposal["total_pence"]},
    )

    session.expire_all()
    stored = session.get(Week, week.id)
    for amount in (
        stored.settled_basic_pence,
        stored.settled_bonus_pence,
        stored.settled_reward_pence,
        stored.settled_total_pence,
    ):
        assert isinstance(amount, int)
    for line in stored.settlement_lines:
        assert isinstance(line.amount_pence, int)
        assert isinstance(line.unit_amount_pence, int)
    assert stored.settled_total_pence == sum(
        line.amount_pence for line in stored.settlement_lines
    )
