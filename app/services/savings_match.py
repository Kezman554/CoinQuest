"""Proposing the monthly savings match, and closing a month on it.

The same two-operation shape as app.services.settlement: `propose` replays
the savings ledger and works out what a month is worth, writing nothing —
call it every five minutes and nothing changes. `settle` takes a figure a
parent actually read and agreed, writes it, and closes the month forever.
There is no cron and no lazy computation triggered by the first request after
month end: money moves because a parent chose it, the same way a week does.

There is no separate document in this repository stating the arithmetic —
only a PRD line naming its shape. What follows is the specification as given
for this card, recorded here since nowhere else does:

  * The rate starts at the scheme's configured start rate (seeded at 5%) and
    climbs one percentage point for every consecutive month that had no
    withdrawal in it, up to the scheme's configured ceiling (seeded at 10%).
    A first month with no withdrawal counts as clean, however partial it is —
    it still earns the start rate, the same as any other clean month would if
    there were no history behind it yet.

  * A withdrawal resets the *same* month's own rate to the start rate, not
    only the month after it: the month a withdrawal happens in earns the
    start rate on itself, and that month's low is not the lowest the whole
    month reached but the lowest it reached *after* the withdrawal — the
    "dipped-to" low. A reversal (a reopened week's payment, unwound) is not a
    withdrawal for this purpose; the child did not choose it, and it neither
    resets the ladder nor triggers the dipped-to-low treatment, though it can
    still be the true low of a month that had no real withdrawal.

  * The match is the rate applied to whichever is lower: the month's low, or
    the scheme's configured cap (seeded at £100). The cap tops out the
    *matched portion* of the balance, not the balance itself — a balance past
    the cap keeps earning the same match it would earn exactly at the cap.

  * The opening balance is not a deposit, but it earns the match like one
    from month one: nothing here treats it specially, since it is simply the
    first entry the ledger ever holds and every calculation here starts from
    replaying entries, opening balance included.

Nothing here reopens a settled month — that is deliberately out of scope, a
separate card. A second attempt at a month already settled is refused
cleanly, both by this module and by the table's own unique constraint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.enums import SavingsType
from app.models.savings_match import SavingsMonthMatch
from app.services import savings, scheme_settings
from app.services.authorisation import Authorisation
from app.services.calendar import Period, month_containing, today

#: The ladder's one fixed step: a point per consecutive clean month. Not a
#: scheme setting — the two figures a parent reviews are where the ladder
#: starts and where it stops (SchemeSettings), not how fast it climbs between
#: them.
RATE_STEP_PERCENT = 1


class MonthNotOver(Exception):
    """Raised by settle(), never propose(): a month can be previewed before
    it ends, but not closed on a figure that could still move."""


class NoSavingsYet(Exception):
    """The savings ledger has no entries. There is nothing to match yet."""


class MonthAlreadySettled(Exception):
    """This month is a closed event already. Reopening one is out of scope."""


class ProposalChanged(Exception):
    """The figure agreed no longer matches what the month currently proposes.

    Can only happen if the ledger changed between the two calls — a
    reopened week's reversal landing in this month, say. Storing an amount
    nobody actually agreed to is the one mistake a settled month cannot
    undo, so this refuses rather than settling anyway.
    """


@dataclass(frozen=True)
class MonthlyMatchProposal:
    """What the next unsettled month is worth. Applied to nothing.

    Computable whether or not that month has finished — a screen reading
    "what would this pay right now" is legitimate mid-month, the low and the
    rate replay exactly the same either way. `month_has_ended` is what tells
    the two situations apart: everything else on this month keeps moving
    until it does, and only settle() refuses to close on it before then.
    """

    period_start: date
    period_end: date
    balance_low_pence: int
    had_withdrawal: bool
    rate_percent: int
    cap_pence: int
    match_pence: int
    month_has_ended: bool
    #: However many months in a row, this one included if it is clean so
    #: far, produced `rate_percent` — the true streak, uncapped, which can
    #: run past the ceiling even once the rate itself has stopped climbing.
    clean_months_in_a_row: int


def latest_settled(session: Session) -> SavingsMonthMatch | None:
    """The most recently settled month, or None if none ever has been."""
    return (
        session.query(SavingsMonthMatch)
        .order_by(SavingsMonthMatch.period_start.desc())
        .first()
    )


def settled_months(session: Session) -> list[SavingsMonthMatch]:
    """Every settled month, oldest first."""
    return (
        session.query(SavingsMonthMatch).order_by(SavingsMonthMatch.period_start).all()
    )


def _month_after(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _next_period(session: Session, tz) -> Period:
    """The one month this scheme has not yet settled and settles next.

    Sequential, always: the month right after the latest settled one, or —
    if nothing has ever settled — the month the ledger's very first entry
    falls in. There is no way to ask this for an arbitrary month, because the
    ladder only means anything read in order.
    """
    latest = latest_settled(session)
    if latest is not None:
        return month_containing(_month_after(latest.period_start), tz)

    entries = savings.history(session)
    if not entries:
        raise NoSavingsYet("The savings ledger has no entries yet; nothing to match.")
    return month_containing(entries[0].occurred_on, tz)


def _balance_before_and_within(
    session: Session, period: Period
) -> tuple[int | None, list[tuple[SavingsType, int]]]:
    """The balance just before the month, and every entry inside it in order.

    `before` is None rather than 0 when the ledger has no entry earlier than
    the period at all — the account did not yet exist, and treating that as a
    balance of zero would drag a first partial month's low down to nothing
    even though the opening balance earns the match from the moment it lands.
    """
    before: int | None = None
    within: list[tuple[SavingsType, int]] = []
    for entry in savings.history(session):
        if entry.occurred_on < period.start:
            before = entry.balance_after_pence
        elif period.contains_day(entry.occurred_on):
            within.append((entry.entry_type, entry.balance_after_pence))
    return before, within


def _low_and_had_withdrawal(
    before: int | None, within: list[tuple[SavingsType, int]]
) -> tuple[int, bool]:
    """The figure the match is calculated on, and whether a withdrawal
    happened this month — which decides which figure that is.
    """
    had_withdrawal = any(entry_type is SavingsType.WITHDRAWAL for entry_type, _ in within)

    if not had_withdrawal:
        candidates = ([before] if before is not None else []) + [
            balance for _, balance in within
        ]
        return (min(candidates) if candidates else 0), False

    # The dipped-to low: only the balance from the first withdrawal onward
    # counts, which is what "resets" means here — a high balance earlier in
    # the same month, carried in or built up before the child touched it,
    # does not drag the match down, and does not inflate it either.
    first_withdrawal = next(
        index for index, (entry_type, _) in enumerate(within) if entry_type is SavingsType.WITHDRAWAL
    )
    after = within[first_withdrawal:]
    return min(balance for _, balance in after), True


def _rate_percent(session: Session, *, had_withdrawal: bool) -> int:
    start_rate = scheme_settings.savings_match_start_rate_percent(session)
    if had_withdrawal:
        return start_rate

    previous = latest_settled(session)
    if previous is None:
        return start_rate

    ceiling_rate = scheme_settings.savings_match_ceiling_rate_percent(session)
    return min(previous.rate_percent + RATE_STEP_PERCENT, ceiling_rate)


def _clean_streak(session: Session, *, had_withdrawal: bool) -> int:
    """This month, if it is clean so far, plus however many settled months
    before it were clean too — walking back until the first withdrawal or
    the ledger's own start. Zero for a month a withdrawal has already
    touched."""
    if had_withdrawal:
        return 0

    streak = 1
    for month in reversed(settled_months(session)):
        if month.had_withdrawal:
            break
        streak += 1
    return streak


def match_pence(*, low_pence: int, rate_percent: int, cap_pence: int) -> int:
    """The rate applied to whichever is lower, the low or the cap.

    Rounded to the nearest penny, ties rounding up — the ladder never touches
    a float, and a rate that does not divide the base evenly needs some
    settled rule rather than a silent truncation.

    Public rather than a module-private helper: app.services.lifetime reuses
    this exact formula to recompute the never-withdrawn counterfactual's own
    monthly matches, and a second copy of it living over there is exactly
    the kind of thing that quietly drifts from the one that actually
    settles.
    """
    base = min(low_pence, cap_pence)
    return (base * rate_percent + 50) // 100


def propose(session: Session, tz) -> MonthlyMatchProposal:
    """What the next unsettled month is worth right now. Writes nothing.

    Computable mid-month on purpose — a screen reading "what would this pay
    today" is a legitimate question before the month is over, and the two
    screens that read this (Oliver's savings page, and the parent panel
    that settles it) both need exactly that. `month_has_ended` says whether
    the figures are final; only settle() refuses to close on one that is
    not. Refuses only a ledger with no entries at all, since there is no
    month to match against an account that does not exist yet.
    """
    period = _next_period(session, tz)

    before, within = _balance_before_and_within(session, period)
    low_pence, had_withdrawal = _low_and_had_withdrawal(before, within)
    rate_percent = _rate_percent(session, had_withdrawal=had_withdrawal)
    cap_pence = scheme_settings.savings_match_cap_pence(session)
    match = match_pence(low_pence=low_pence, rate_percent=rate_percent, cap_pence=cap_pence)
    clean_months_in_a_row = _clean_streak(session, had_withdrawal=had_withdrawal)

    return MonthlyMatchProposal(
        period_start=period.start,
        period_end=period.end,
        balance_low_pence=low_pence,
        had_withdrawal=had_withdrawal,
        rate_percent=rate_percent,
        cap_pence=cap_pence,
        match_pence=match,
        month_has_ended=today(tz) > period.end,
        clean_months_in_a_row=clean_months_in_a_row,
    )


def settle(
    session: Session,
    proposal: MonthlyMatchProposal,
    authorisation: Authorisation,
    *,
    agreed_match_pence: int,
) -> SavingsMonthMatch:
    """Close a month on a figure a parent has read and agreed.

    Checked against a fresh existence test rather than trusted from the
    proposal alone — the same defence settlement.settle applies to a week's
    status — so two requests racing to settle the same month cannot both
    succeed, and the table's own unique constraint stands behind this as the
    last word if they somehow still tried to.

    Refuses a proposal whose month has not finished yet: propose() will
    compute one anyway, for a screen reading how the month stands so far,
    but the low it reports is not final until the month is, and settling on
    it would store a figure the rest of the month could still have moved.
    """
    if not proposal.month_has_ended:
        raise MonthNotOver(
            f"{proposal.period_start.isoformat()} has not finished yet;"
            " there is nothing final to settle."
        )

    already = (
        session.query(SavingsMonthMatch)
        .filter(SavingsMonthMatch.period_start == proposal.period_start)
        .first()
    )
    if already is not None:
        raise MonthAlreadySettled(
            f"{proposal.period_start.isoformat()} is already settled."
        )

    if agreed_match_pence != proposal.match_pence:
        raise ProposalChanged(
            f"This month now proposes {proposal.match_pence}p, not"
            f" {agreed_match_pence}p. Read the figures again before agreeing."
        )

    entry = savings.record_match(
        session,
        amount_pence=proposal.match_pence,
        occurred_on=proposal.period_end,
        reason=f"Savings match for {proposal.period_start.strftime('%B %Y')}",
    )

    row = SavingsMonthMatch(
        period_start=proposal.period_start,
        period_end=proposal.period_end,
        balance_low_pence=proposal.balance_low_pence,
        had_withdrawal=proposal.had_withdrawal,
        rate_percent=proposal.rate_percent,
        cap_pence=proposal.cap_pence,
        match_pence=proposal.match_pence,
        match_entry_id=entry.id,
        settled_by=authorisation.party,
        settled_at=authorisation.at,
    )
    session.add(row)
    session.flush()
    return row
