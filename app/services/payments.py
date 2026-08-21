"""Payday: handing over what closed weeks owe, and banking part of it.

Settling and paying are two different acts, deliberately. A week settles on a
Sunday when a parent agrees its figures; the money changes hands when somebody
is next at a cash machine. Between those two moments the week is settled and
owed, which is a state the app has to be able to show — otherwise "did we
actually pay him for that week?" is a question only somebody's memory can
answer, which is the problem this whole app exists to solve.

One payment may clear several weeks at once, because that is how it actually
happens: two weeks go by, and then all of it is handed over together.

What the child chooses to bank is recorded against the weeks it came from and
written to the savings ledger. What he keeps is not recorded anywhere at all.
Cash in a pocket is not this app's business, and pretending to track it would
produce a number that is wrong within a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.enums import EarningType, WeekStatus
from app.models.ledgers import EarningEntry
from app.models.weeks import Week
from app.services import savings
from app.services.authorisation import Authorisation


class PaymentError(Exception):
    """Something about this payment does not add up."""


@dataclass(frozen=True)
class Owed:
    """One closed week and what it comes to."""

    week_id: int
    start_date: date
    end_date: date
    settled_total_pence: int
    reward_pence: int
    owed_pence: int
    is_paid: bool


def amount_owed(session: Session, week: Week) -> int:
    """What this week comes to: its settled figures, plus anything entered
    against it afterwards.

    A parent-entered reward belongs to the week it was entered in and is
    independent of the chore result, so it never touches the settled figures —
    but it is still money owed, and payday hands it over with the rest.
    """
    if week.settled_total_pence is None:
        return 0
    return week.settled_total_pence + ad_hoc_rewards(session, week.id)


def ad_hoc_rewards(session: Session, week_id: int) -> int:
    """Rewards entered against this week by a parent.

    Public because the week view needs it too. A reward never touches the
    week's settled figures — a bad week at the hoover does not make an award
    smaller — but it is money the child is owed for that week, so a screen
    that leaves it out of "what this week comes to" is wrong about the money.
    """
    return sum(
        entry.amount_pence
        for entry in session.query(EarningEntry).filter(
            EarningEntry.week_id == week_id,
            EarningEntry.entry_type == EarningType.REWARD,
        )
    )


def outstanding(session: Session) -> list[Owed]:
    """Every closed week that has not been paid yet, oldest first."""
    weeks = (
        session.query(Week)
        .filter(Week.status.in_([WeekStatus.SETTLED, WeekStatus.VOIDED]))
        .filter(Week.paid_at.is_(None))
        .order_by(Week.start_date)
        .all()
    )
    return [describe(session, week) for week in weeks]


def describe(session: Session, week: Week) -> Owed:
    return Owed(
        week_id=week.id,
        start_date=week.start_date,
        end_date=week.end_date,
        settled_total_pence=week.settled_total_pence or 0,
        reward_pence=ad_hoc_rewards(session, week.id),
        owed_pence=amount_owed(session, week),
        is_paid=week.paid_at is not None,
    )


@dataclass(frozen=True)
class Payment:
    """One handing-over, covering one or more weeks."""

    week_ids: tuple[int, ...]
    paid_pence: int
    deposited_pence: int
    kept_pence: int
    occurred_on: date
    balance_after_pence: int


def pay(
    session: Session,
    weeks: list[Week],
    authorisation: Authorisation,
    *,
    deposited_pence: int,
    occurred_on: date,
) -> Payment:
    """Mark weeks paid, and bank the part the child chose to keep back.

    The deposit is apportioned across the weeks in date order, so each week
    records how much of it came from that payday and the savings ledger says
    which week each deposit came from. That apportioning is bookkeeping, not a
    decision: the child decided one number, and it is the total.
    """
    if not weeks:
        raise PaymentError("A payment has to cover at least one week.")

    for week in weeks:
        if week.status is WeekStatus.OPEN:
            raise PaymentError(
                f"Week {week.start_date.isoformat()} has not been settled yet."
                " Settling and paying are separate acts, in that order."
            )
        if week.paid_at is not None:
            raise PaymentError(
                f"Week {week.start_date.isoformat()} was already paid on"
                f" {week.paid_at.date().isoformat()}."
            )

    paid_pence = sum(amount_owed(session, week) for week in weeks)

    if deposited_pence < 0:
        raise PaymentError("A deposit cannot be negative.")
    if deposited_pence > paid_pence:
        raise PaymentError(
            f"This payment is {paid_pence}p; {deposited_pence}p cannot be put"
            " aside from it."
        )

    remaining = deposited_pence
    for week in sorted(weeks, key=lambda w: w.start_date):
        owed = amount_owed(session, week)
        share = min(remaining, owed)
        week.paid_at = authorisation.at
        week.deposited_pence = share
        remaining -= share

        if share:
            savings.record_deposit(
                session,
                amount_pence=share,
                occurred_on=occurred_on,
                week_id=week.id,
                reason=f"Deposited from the payday for week {week.start_date.isoformat()}",
            )

    session.flush()
    return Payment(
        week_ids=tuple(week.id for week in weeks),
        paid_pence=paid_pence,
        deposited_pence=deposited_pence,
        # Recorded here for the response and stored nowhere. What he keeps is
        # his, and this app does not follow it around.
        kept_pence=paid_pence - deposited_pence,
        occurred_on=occurred_on,
        balance_after_pence=savings.current_balance(session),
    )
