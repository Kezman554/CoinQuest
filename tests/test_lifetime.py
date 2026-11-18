"""Lifetime totals, and the never-withdrawn comparison.

The counterfactual trajectory is checked two ways: against a hand-worked
example, and — the stronger proof — against the real ladder itself. When
nothing has ever actually been withdrawn, replaying the same deposits with
withdrawals filtered out (a no-op filter, in that case) and recomputing each
month's match must land on exactly the figures the real ladder already
settled on, since both read the same live scheme_settings. That equality is
what test_matches_the_real_ladder_when_nothing_was_ever_withdrawn asserts.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models.base import utcnow
from app.models.enums import SavingsType
from app.models.ledgers import EarningEntry, SavingsEntry
from app.services import lifetime, savings, savings_match
from app.services.authorisation import Authorisation

PIN = "0000"
CHILD = "Test Child"
PARENT = "Test Parent"


@pytest.fixture()
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def tz(session):
    from app.config import get_settings

    return get_settings().tzinfo


def opening_balance(session, *, amount_pence=1000, on=date(2026, 1, 10)):
    return savings.record_opening_balance(session, amount_pence=amount_pence, occurred_on=on)


def deposit(session, *, amount_pence, on):
    return savings.record_deposit(session, amount_pence=amount_pence, occurred_on=on)


def withdraw(session, *, amount_pence, on, reason="Toy"):
    return savings.record_withdrawal(session, amount_pence=amount_pence, occurred_on=on, reason=reason)


def settle_next_month(session, tz):
    proposal = savings_match.propose(session, tz)
    authorisation = Authorisation(party="parent", at=utcnow())
    row = savings_match.settle(
        session, proposal, authorisation, agreed_match_pence=proposal.match_pence
    )
    session.commit()
    return row


def payday_deposit(api, session, *, deposited_pence, week_start=date(2026, 1, 4)):
    """A real payday deposit — settle a perfect week, then bank part of it —
    rather than a bare savings.record_deposit call, so this exercises the
    actual week_id-carrying path app.services.payments writes."""
    from app.models import Cadence, Category, ChoreDefinition, ChoreInstance, InstanceState, Week
    from app.services import scheme_settings

    beds = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=0
    )
    session.add(beds)
    scheme_settings.get_row(session).weekly_basic_pay_pence = 350
    session.commit()

    week = Week(start_date=week_start, end_date=date.fromordinal(week_start.toordinal() + 6))
    session.add(week)
    session.commit()
    for offset in range(7):
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(week.start_date.toordinal() + offset),
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
        )
    session.commit()

    assert api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    ).status_code == 200
    response = api.post(
        "/api/weeks/payments",
        json={"pin": PIN, "week_ids": [week.id], "deposited_pence": deposited_pence},
    )
    assert response.status_code == 200
    return week


def settle_every_elapsed_month(session, tz):
    """Every month up to today that has actually finished — not a fixed
    count, so the "nothing was ever withdrawn" equality test holds however
    much real time separates the opening balance from whenever this runs."""
    while True:
        proposal = savings_match.propose(session, tz)
        if not proposal.month_has_ended:
            return
        settle_next_month(session, tz)


# --- Total earned ------------------------------------------------------


def test_total_earned_sums_every_earnings_ledger_entry(session):
    from app.models import Week

    first_week = Week(start_date=date(2026, 1, 4), end_date=date(2026, 1, 10))
    second_week = Week(start_date=date(2026, 1, 11), end_date=date(2026, 1, 17))
    session.add_all([first_week, second_week])
    session.commit()

    session.add_all(
        [
            EarningEntry(
                entry_type="week_settlement",
                amount_pence=450,
                week_id=first_week.id,
                occurred_on=date(2026, 1, 10),
            ),
            EarningEntry(
                entry_type="reward",
                amount_pence=200,
                occurred_on=date(2026, 1, 6),
                reason="Eagle award",
            ),
            EarningEntry(
                entry_type="week_settlement",
                amount_pence=0,
                week_id=second_week.id,
                occurred_on=date(2026, 1, 17),
            ),
        ]
    )
    session.commit()

    assert lifetime.total_earned_pence(session) == 650


def test_total_earned_is_zero_with_no_history(session):
    assert lifetime.total_earned_pence(session) == 0


def test_total_earned_includes_a_settled_week_and_an_ad_hoc_reward(api, session):
    from app.models import Cadence, Category, ChoreDefinition, ChoreInstance, InstanceState, Week

    beds = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=0
    )
    session.add(beds)
    from app.services import scheme_settings

    scheme_settings.get_row(session).weekly_basic_pay_pence = 350
    session.commit()

    week = Week(start_date=date(2026, 1, 4), end_date=date(2026, 1, 10))
    session.add(week)
    session.commit()
    for offset in range(7):
        session.add(
            ChoreInstance(
                definition_id=beds.id,
                week_id=week.id,
                due_date=date.fromordinal(week.start_date.toordinal() + offset),
                state=InstanceState.CONFIRMED,
                confirmed_at=week.created_at,
                authorised_by="parent",
            )
        )
    session.commit()

    settle = api.post(
        f"/api/weeks/{week.id}/settle", json={"pin": PIN, "agreed_total_pence": 450}
    )
    assert settle.status_code == 200

    reward = api.post("/api/rewards", json={"pin": PIN, "amount": "£2", "reason": "Well done"})
    assert reward.status_code == 201

    body = api.get("/api/lifetime").json()
    assert body["total_earned_pence"] == 650


# --- The real trajectory: a straight read -----------------------------------


def test_real_trajectory_matches_the_savings_ledgers_own_history(session):
    opening_balance(session, amount_pence=1000, on=date(2026, 1, 5))
    deposit(session, amount_pence=500, on=date(2026, 1, 20))
    withdraw(session, amount_pence=300, on=date(2026, 1, 25))
    session.commit()

    points = lifetime.real_trajectory(session)
    history = savings.history(session)

    assert [p.balance_pence for p in points] == [e.balance_after_pence for e in history]
    assert [p.occurred_on for p in points] == [e.occurred_on for e in history]


def test_an_empty_ledger_has_no_real_trajectory(session):
    assert lifetime.real_trajectory(session) == []


# --- The counterfactual ------------------------------------------------


def test_counterfactual_is_empty_with_no_history(session, tz):
    assert lifetime.counterfactual_trajectory(session, tz) == []


def test_a_month_in_progress_adds_no_match_to_either_trajectory(session, tz):
    from app.services.calendar import today

    opening_balance(session, amount_pence=1000, on=today(tz).replace(day=1))
    session.commit()

    real = lifetime.real_trajectory(session)
    counterfactual = lifetime.counterfactual_trajectory(session, tz)

    assert [p.balance_pence for p in real] == [1000]
    assert [p.balance_pence for p in counterfactual] == [1000]


def test_matches_the_real_ladder_when_nothing_was_ever_withdrawn(session, tz):
    """The strong proof: with no withdrawal in reality, replaying "kept"
    entries (a no-op filter here) and recomputing each month's match must
    reproduce exactly what the real ladder already settled on, since both
    read the same live scheme_settings."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    settle_every_elapsed_month(session, tz)

    counterfactual = lifetime.counterfactual_trajectory(session, tz)
    assert counterfactual[-1].balance_pence == savings.current_balance(session)

    # And every point along the way agrees, not only the final figure.
    real = lifetime.real_trajectory(session)
    assert [p.balance_pence for p in counterfactual] == [p.balance_pence for p in real]


def test_the_counterfactual_pulls_ahead_once_a_real_withdrawal_resets_the_ladder(session, tz):
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    for _ in range(3):
        settle_next_month(session, tz)

    # A withdrawal in the fourth month resets the real ladder to 5%.
    withdraw(session, amount_pence=10_00, on=date(2026, 4, 10))
    session.commit()
    settle_next_month(session, tz)

    for _ in range(2):
        settle_next_month(session, tz)

    real_balance = savings.current_balance(session)
    counterfactual = lifetime.counterfactual_trajectory(session, tz)

    # The counterfactual never saw the withdrawal, so its ladder climbed
    # straight through where the real one reset — it must be worth more.
    assert counterfactual[-1].balance_pence > real_balance
    # And its principal is the same £100 that was actually put in, plus
    # match only — the withdrawal itself is simply absent, not refunded.
    assert counterfactual[-1].balance_pence > 100_00


def test_a_reversal_still_reduces_the_counterfactual(session, tz):
    """Unlike a withdrawal, a reversal is not the child's choice — it
    corrects a deposit that should not have counted — so it stays in the
    counterfactual's own balance."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.add(
        SavingsEntry(
            entry_type=SavingsType.REVERSAL,
            amount_pence=-20_00,
            balance_after_pence=80_00,
            occurred_on=date(2026, 1, 12),
            reason="Reversed: a week reopened",
        )
    )
    session.commit()

    counterfactual = lifetime.counterfactual_trajectory(session, tz)
    # The point right after the reversal reflects it.
    assert 80_00 in [p.balance_pence for p in counterfactual]


# --- The endpoint ------------------------------------------------------


def test_reading_needs_no_pin(api):
    assert api.get("/api/lifetime").status_code == 200


def test_the_endpoint_is_empty_and_not_an_error_with_no_history(api):
    body = api.get("/api/lifetime").json()
    assert body == {
        "total_earned_pence": 0,
        "savings_breakdown": {
            "from_payday_pence": 0,
            "from_gifts_pence": 0,
            "from_match_pence": 0,
        },
        "real": [],
        "counterfactual": [],
        "saved_everything": [],
    }


def test_the_endpoint_reports_both_trajectories(api, session):
    from app.services.calendar import today
    from app.config import get_settings

    first_of_this_month = today(get_settings().tzinfo).replace(day=1)
    opening_balance(session, amount_pence=1000, on=first_of_this_month)
    withdraw(session, amount_pence=200, on=first_of_this_month)
    session.commit()

    body = api.get("/api/lifetime").json()
    # The month is still in progress, so neither trajectory has reached a
    # match yet — the real one shows the withdrawal, the counterfactual
    # simply does not see it happen.
    assert [p["balance_pence"] for p in body["real"]] == [1000, 800]
    assert [p["balance_pence"] for p in body["counterfactual"]] == [1000]


# --- The savings breakdown --------------------------------------------------


def test_a_payday_deposit_counts_under_from_payday(api, session):
    payday_deposit(api, session, deposited_pence=200)

    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_payday_pence == 200
    assert breakdown.from_gifts_pence == 0
    assert breakdown.from_match_pence == 0


def test_a_confirmed_standalone_deposit_counts_as_a_gift_not_payday(api, session):
    """The exact case the card asks to be tested: log an ad hoc deposit and
    confirm it lands under gifts/ad-hoc, not payday."""
    payday_deposit(api, session, deposited_pence=200)

    request = api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    ).json()
    confirmed = api.post(
        f"/api/savings/deposits/{request['id']}/confirm", json={"pin": PIN}
    )
    assert confirmed.status_code == 200

    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_gifts_pence == 500
    assert breakdown.from_payday_pence == 200


def test_a_parent_posted_deposit_also_counts_as_a_gift(api, session):
    response = api.post(
        "/api/savings/deposits/parent",
        json={"pin": PIN, "amount_pence": 300, "note": "Gift from Grandma", "posted_by": PARENT},
    )
    assert response.status_code == 201

    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_gifts_pence == 300
    assert breakdown.from_payday_pence == 0


def test_a_pending_unconfirmed_deposit_counts_nowhere_yet(api, session):
    """A submitted-but-not-confirmed deposit has not reached the ledger at
    all — see app.services.savings_deposits. Neither breakdown figure
    should see it until a parent confirms it."""
    opening_balance(session, amount_pence=1000)
    session.commit()
    api.post(
        "/api/savings/deposits",
        json={"amount_pence": 500, "note": "Birthday money", "posted_by": CHILD},
    )

    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_gifts_pence == 0


def test_the_opening_balance_entry_counts_toward_neither_bucket(session):
    """OPENING_BALANCE is not a DEPOSIT, and this breakdown is not asked to
    account for it — the card names payday and standalone deposits, plus
    the match, as the three sources; an opening balance entered through the
    now-legacy dedicated endpoint is deliberately outside all three, the
    same way it is outside total_earned_pence."""
    opening_balance(session, amount_pence=1000)

    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_payday_pence == 0
    assert breakdown.from_gifts_pence == 0


def test_the_match_figure_is_the_sum_of_every_settled_months_match(session, tz):
    """Not recomputed — totalled from the same rows the monthly-match
    history already stores."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    for _ in range(4):
        settle_next_month(session, tz)

    expected = sum(month.match_pence for month in savings_match.settled_months(session))
    assert expected > 0  # sanity: the ladder actually paid something

    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_match_pence == expected


def test_a_withdrawal_month_still_contributes_its_match(session, tz):
    """A withdrawal resets the rate, not the fact that the month still
    settles on some figure — that figure still belongs in the total."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()
    settle_next_month(session, tz)  # January, clean

    withdraw(session, amount_pence=10_00, on=date(2026, 2, 10))
    session.commit()
    settle_next_month(session, tz)  # February, reset by the withdrawal

    expected = sum(month.match_pence for month in savings_match.settled_months(session))
    breakdown = lifetime.savings_breakdown(session)
    assert breakdown.from_match_pence == expected


def test_the_endpoint_reports_the_breakdown(api, session):
    payday_deposit(api, session, deposited_pence=200)
    api.post(
        "/api/savings/deposits/parent",
        json={"pin": PIN, "amount_pence": 300, "note": "Gift", "posted_by": PARENT},
    )

    body = api.get("/api/lifetime").json()
    assert body["savings_breakdown"] == {
        "from_payday_pence": 200,
        "from_gifts_pence": 300,
        "from_match_pence": 0,
    }


def test_the_counterfactual_still_renders_with_a_standalone_deposit_included(api, session, tz):
    """The chart needs no changes to pick up an ad hoc deposit — it already
    replays every DEPOSIT-type entry regardless of source. Proved here
    rather than assumed."""
    opening_balance(session, amount_pence=100_00, on=date(2026, 1, 5))
    session.commit()

    gift = api.post(
        "/api/savings/deposits/parent",
        json={"pin": PIN, "amount_pence": 20_00, "note": "Birthday money", "posted_by": PARENT},
    )
    assert gift.status_code == 201

    settle_every_elapsed_month(session, tz)

    body = api.get("/api/lifetime").json()
    assert body["counterfactual"], "the chart has points to draw"
    # The gift is real money in the account; the counterfactual's final
    # balance has to reflect it, the same as the real trajectory does.
    assert body["counterfactual"][-1]["balance_pence"] == body["real"][-1]["balance_pence"]
    assert body["real"][-1]["balance_pence"] >= 100_00 + 20_00


# --- If every week's pay had been saved (Session AT) ------------------------


def closed_week(session, *, start, pay_pence, tz):
    """A week settled as stored: its figures written once, closed on the
    Sunday after it ended (noon, London)."""
    from datetime import datetime, time, timedelta

    from app.models import Week
    from app.models.enums import WeekStatus

    end = start + timedelta(days=6)
    closed_on = end + timedelta(days=1)
    week = Week(
        start_date=start,
        end_date=end,
        status=WeekStatus.SETTLED,
        settled_base_pence=pay_pence,
        settled_chore_pay_pence=0,
        settled_bonus_pence=0,
        settled_reward_pence=0,
        settled_total_pence=pay_pence,
        closed_at=datetime.combine(closed_on, time(12), tzinfo=tz),
    )
    session.add(week)
    session.flush()
    return week, closed_on


def seeded_history(session, tz):
    """Six months of a real-looking account, all of it in the past: an
    opening balance, twelve weeks each paying £4.50 with £1.50 of it banked
    on the day it closed, a birthday gift, a withdrawal, and one week that
    was banked, reopened (its deposit reversed) and is open again."""
    from datetime import timedelta

    from app.models import Week

    opening_balance(session, amount_pence=10_00, on=date(2026, 1, 5))
    paid = []
    start = date(2026, 1, 4)  # a Sunday
    for _ in range(12):
        week, closed_on = closed_week(session, start=start, pay_pence=450, tz=tz)
        savings.record_deposit(session, amount_pence=150, occurred_on=closed_on, week_id=week.id)
        paid.append(week)
        start += timedelta(days=7)
    deposit(session, amount_pence=5_00, on=date(2026, 2, 14))
    withdraw(session, amount_pence=3_00, on=date(2026, 3, 10))

    reopened = Week(start_date=start, end_date=start + timedelta(days=6))
    session.add(reopened)
    session.flush()
    savings.record_deposit(session, amount_pence=150, occurred_on=date(2026, 4, 5), week_id=reopened.id)
    savings.record_reversal(
        session, amount_pence=150, occurred_on=date(2026, 4, 9), week_id=reopened.id,
        reason="Reversed: a week reopened",
    )
    session.commit()
    return paid


def test_saving_everything_grows_by_more_than_the_extra_money_put_in(session, tz):
    """The extra money is every closed week's full pay less what payday
    really banked. Matched month after month on a higher low, the line ends
    further above the never-withdrawn one than that extra alone."""
    paid = seeded_history(session, tz)
    full_pay = sum(450 for _ in paid)
    really_banked = sum(
        entry.amount_pence for entry in savings.history(session) if entry.week_id is not None
    )
    extra = full_pay - really_banked
    assert extra == 12 * 450 - 12 * 150  # the reopened week's deposit and reversal net out

    never_withdrawn = lifetime.counterfactual_trajectory(session, tz)
    saved_everything = lifetime.saved_everything_trajectory(session, tz)

    gap = saved_everything[-1].balance_pence - never_withdrawn[-1].balance_pence
    assert gap > extra


def test_saving_everything_is_never_below_never_withdrawn_at_a_month_end(session, tz):
    seeded_history(session, tz)
    never_withdrawn = {p.occurred_on: p.balance_pence for p in lifetime.counterfactual_trajectory(session, tz)}
    saved_everything = {p.occurred_on: p.balance_pence for p in lifetime.saved_everything_trajectory(session, tz)}
    shared = sorted(set(never_withdrawn) & set(saved_everything))
    assert shared  # the month ends both lines reach
    for day in shared:
        assert saved_everything[day] >= never_withdrawn[day], day


def test_saving_everything_replaces_payday_and_keeps_the_rest(session, tz):
    """Payday's own deposit is replaced by the week's whole pay, on the day
    the week closed — not added to it. The opening balance and the gift stay
    exactly as they happened. February 2026, to its first match."""
    opening_balance(session, amount_pence=10_00, on=date(2026, 2, 2))
    deposit(session, amount_pence=5_00, on=date(2026, 2, 3))
    week, closed_on = closed_week(session, start=date(2026, 2, 1), pay_pence=450, tz=tz)
    assert closed_on == date(2026, 2, 8)
    savings.record_deposit(session, amount_pence=150, occurred_on=closed_on, week_id=week.id)
    session.commit()

    never_withdrawn = lifetime.counterfactual_trajectory(session, tz)
    saved_everything = lifetime.saved_everything_trajectory(session, tz)

    assert [(p.occurred_on, p.balance_pence) for p in never_withdrawn[:3]] == [
        (date(2026, 2, 2), 10_00),
        (date(2026, 2, 3), 15_00),
        (date(2026, 2, 8), 16_50),
    ]
    assert [(p.occurred_on, p.balance_pence) for p in saved_everything[:4]] == [
        (date(2026, 2, 2), 10_00),
        (date(2026, 2, 3), 15_00),
        (date(2026, 2, 8), 19_50),  # 4.50 in place of the 1.50, not beside it
        # February's match: the start rate on the month's low, as the real ladder.
        (date(2026, 2, 28), 19_50 + savings_match.match_pence(
            low_pence=10_00,
            rate_percent=scheme_settings_start_rate(session),
            cap_pence=scheme_settings_cap(session),
        )),
    ]


def scheme_settings_start_rate(session):
    from app.services import scheme_settings

    return scheme_settings.savings_match_start_rate_percent(session)


def scheme_settings_cap(session):
    from app.services import scheme_settings

    return scheme_settings.savings_match_cap_pence(session)


def test_an_open_week_adds_nothing_until_it_closes(session, tz):
    seeded_history(session, tz)
    before = lifetime.saved_everything_trajectory(session, tz)

    from app.models import Week

    session.add(Week(start_date=date(2026, 11, 15), end_date=date(2026, 11, 21)))
    session.commit()
    assert lifetime.saved_everything_trajectory(session, tz) == before


def test_a_later_rule_change_does_not_rewrite_the_line(session, tz):
    """The pay is read from each week's stored settlement, so a change to
    what a week pays now reaches nothing already closed."""
    from app.services import scheme_settings

    seeded_history(session, tz)
    before = lifetime.saved_everything_trajectory(session, tz)
    scheme_settings.get_row(session).weekly_basic_pay_pence = 9_99
    session.commit()
    assert lifetime.saved_everything_trajectory(session, tz) == before


def test_the_replay_writes_nothing(session, tz):
    from app.models import Week

    seeded_history(session, tz)
    counts = (session.query(SavingsEntry).count(), session.query(EarningEntry).count(), session.query(Week).count())
    balance = savings.current_balance(session)

    lifetime.saved_everything_trajectory(session, tz)
    session.commit()

    assert (session.query(SavingsEntry).count(), session.query(EarningEntry).count(), session.query(Week).count()) == counts
    assert savings.current_balance(session) == balance


def test_the_endpoint_reports_the_saved_everything_line(api, session, tz):
    seeded_history(session, tz)
    body = api.get("/api/lifetime").json()
    assert body["saved_everything"]
    assert body["saved_everything"][-1]["balance_pence"] > body["counterfactual"][-1]["balance_pence"]
