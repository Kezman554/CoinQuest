"""Lifetime totals, and the never-withdrawn comparison.

Nothing here is stored. Every figure is rebuilt fresh from the existing
ledgers on every read — no new table, no cache, no field on an existing one.

`total_earned_pence` is everything the earnings ledger has ever recorded,
added up. Base, chore pay, bonuses, chore-category rewards and ad-hoc
rewards are already one append-only entry each — `EarningEntry`, written by
`settlement.settle`/`settlement.void` for a week and by the rewards router
for an ad-hoc one (see app.models.ledgers) — independent of whether the
money was later kept as cash or banked. Summing that ledger is the whole
computation; nothing here re-derives an amount from a chore definition or a
week's own columns.

`savings_breakdown` answers a different question — not everything ever
earned, but why what is actually in the account got there: split into what
came from a payday, what came in as a standalone deposit (a gift, birthday
money — see app.services.savings_deposits), and what the account earned
purely by being left alone, added up from every month the match has
actually settled. See SavingsBreakdown.

The never-withdrawn comparison is two trajectories of the savings balance
over time:

  `real_trajectory` is exactly what the savings ledger already recorded,
  withdrawals included — a straight read of app.services.savings.history.

  `counterfactual_trajectory` replays the same deposits (and reversals — see
  `_KEPT_TYPES` for why a reversal stays in while a withdrawal does not)
  against a balance of its own, skipping every withdrawal outright so the
  match ladder never resets, and recomputes each finished month's match
  under that assumption with `savings_match.match_pence` — the exact formula
  the real ladder uses, reused rather than reimplemented, because a second
  copy of that arithmetic living here is exactly the kind of thing that
  quietly drifts from the one that actually settles. It reads scheme_settings
  live, the same way `savings_match.propose` does for the one real month
  still open — this is a fresh "what if" recomputation, not an attempt to
  reproduce whatever the ladder happened to be worth on some past date.

"How money grows if you leave it alone" is the intended framing on any
screen that reads this, not "what you would have had" — the counterfactual
is a lesson about not withdrawing, not a running total of a grievance about
money already spent. That framing is the spec's, not this module's to
relitigate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import SavingsType
from app.models.ledgers import EarningEntry, SavingsEntry
from app.services import savings, savings_match, scheme_settings
from app.services.calendar import month_containing, today


@dataclass(frozen=True)
class BalancePoint:
    occurred_on: date
    balance_pence: int


@dataclass(frozen=True)
class SavingsBreakdown:
    """Why the money actually in the account is there, split three ways.

    A different question from total_earned_pence, and a different total: not
    everything ever earned, cash or banked, but only what was ever deposited
    or matched — the positive side of the savings ledger, broken down by
    source rather than added into one figure. from_match_pence in particular
    is not earned by anything he did; it exists because leaving money in the
    account pays on its own.
    """

    #: DEPOSIT entries that split off a payday (see app.services.payments) —
    #: identified by carrying a week_id, the same way those entries always
    #: have.
    from_payday_pence: int
    #: DEPOSIT entries with no week_id: a standalone deposit, confirmed from
    #: Oliver or posted directly by a parent (see
    #: app.services.savings_deposits) — birthday money, a gift, anything
    #: that did not come from a payday split.
    from_gifts_pence: int
    #: Every settled month's match, added up. Read from
    #: savings_match.settled_months rather than recomputed — those rows are
    #: the actual figures a month closed on, and this totals them rather
    #: than re-deriving anything from the ladder.
    from_match_pence: int


def total_earned_pence(session: Session) -> int:
    """Everything ever earned, added up. See the module note."""
    total = session.query(func.sum(EarningEntry.amount_pence)).scalar()
    return total or 0


def savings_breakdown(session: Session) -> SavingsBreakdown:
    """The account's own money, split by why it's there. See SavingsBreakdown."""
    from_payday = (
        session.query(func.sum(SavingsEntry.amount_pence))
        .filter(
            SavingsEntry.entry_type == SavingsType.DEPOSIT,
            SavingsEntry.week_id.isnot(None),
        )
        .scalar()
    ) or 0
    from_gifts = (
        session.query(func.sum(SavingsEntry.amount_pence))
        .filter(
            SavingsEntry.entry_type == SavingsType.DEPOSIT,
            SavingsEntry.week_id.is_(None),
        )
        .scalar()
    ) or 0
    from_match = sum(month.match_pence for month in savings_match.settled_months(session))

    return SavingsBreakdown(
        from_payday_pence=from_payday,
        from_gifts_pence=from_gifts,
        from_match_pence=from_match,
    )


def real_trajectory(session: Session) -> list[BalancePoint]:
    """The savings balance over time, exactly as the ledger recorded it —
    every deposit, every withdrawal, every match actually settled."""
    return [
        BalancePoint(occurred_on=entry.occurred_on, balance_pence=entry.balance_after_pence)
        for entry in savings.history(session)
    ]


#: Entry types the counterfactual keeps. A withdrawal is the one thing this
#: whole comparison is asking "what if that never happened" about, so it is
#: skipped outright here — not merely excluded from a month's low the way it
#: is in the real ladder (savings_match._low_and_had_withdrawal), but absent
#: from the balance altogether, as if it had never been taken out. A
#: reversal stays: it is not the child's withdrawal, it is a correction to
#: what was actually deposited (a reopened week's payment, unwound — see
#: settlement.reopen), and dropping it would let the counterfactual count
#: money that was never really banked. A match is never replayed from the
#: real ledger — the counterfactual computes its own, from its own balance
#: and its own ladder, which is the entire point of it.
_KEPT_TYPES = frozenset(
    {SavingsType.OPENING_BALANCE, SavingsType.DEPOSIT, SavingsType.REVERSAL}
)


def _month_after(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def counterfactual_trajectory(session: Session, tz) -> list[BalancePoint]:
    """What the balance would be if no withdrawal had ever happened.

    Walks the same calendar months savings_match.propose walks for the real
    ladder, one at a time from the first kept entry's month to the current
    one, but over a balance of its own that a real withdrawal never touches.
    A month still in progress contributes its deposits so far and no match —
    the same "final only once the month has ended" rule the real ladder
    applies, so the two trajectories stay comparable at any point in time
    rather than one of them projecting ahead of the other.
    """
    kept = [
        (entry.occurred_on, entry.amount_pence)
        for entry in savings.history(session)
        if entry.entry_type in _KEPT_TYPES
    ]
    if not kept:
        return []

    start_rate = scheme_settings.savings_match_start_rate_percent(session)
    ceiling_rate = scheme_settings.savings_match_ceiling_rate_percent(session)
    cap_pence = scheme_settings.savings_match_cap_pence(session)

    points: list[BalancePoint] = []
    balance: int | None = None  # None until the first kept entry lands —
    # same reason savings_match._balance_before_and_within treats "before"
    # this way: the account did not exist yet, and a phantom zero would
    # drag a first partial month's low down to nothing.
    previous_rate: int | None = None
    index = 0
    month_start = month_containing(kept[0][0], tz).start
    today_date = today(tz)

    while month_start <= today_date:
        period = month_containing(month_start, tz)
        before = balance
        within_balances: list[int] = []

        while index < len(kept) and period.contains_day(kept[index][0]):
            occurred_on, amount = kept[index]
            balance = (balance or 0) + amount
            within_balances.append(balance)
            points.append(BalancePoint(occurred_on=occurred_on, balance_pence=balance))
            index += 1

        if today_date > period.end and balance is not None:
            candidates = ([before] if before is not None else []) + within_balances
            low = min(candidates)
            rate = (
                start_rate
                if previous_rate is None
                else min(previous_rate + savings_match.RATE_STEP_PERCENT, ceiling_rate)
            )
            match = savings_match.match_pence(
                low_pence=low, rate_percent=rate, cap_pence=cap_pence
            )
            balance += match
            points.append(BalancePoint(occurred_on=period.end, balance_pence=balance))
            previous_rate = rate

        month_start = _month_after(period.start)

    return points
