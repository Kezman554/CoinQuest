"""The savings ledger.

The ledger has been kept from the first payday, well before anything computed
a match from it — because the match rewards money left alone and that can
only be worked out from a balance history nobody kept at the time. Deferring
the feature was a choice about when to build something; deferring the record
would have been a choice to make the feature impossible when it arrived. The
first is reversible and the second is not. See app.services.savings_match for
the match itself, computed by replaying exactly this ledger.

Every entry carries the balance after it. That is a running total written once
into a row that cannot be edited — not a mutable field that could drift out of
step with the entries that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.enums import SavingsType
from app.models.ledgers import SavingsEntry


class SavingsError(Exception):
    """Something the ledger will not accept."""


def current_balance(session: Session) -> int:
    """The balance after the most recent entry, or zero if there are none."""
    latest = (
        session.query(SavingsEntry)
        .order_by(SavingsEntry.id.desc())
        .first()
    )
    return latest.balance_after_pence if latest else 0


@dataclass(frozen=True)
class Reconciliation:
    """The ledger's balance beside what the real account holds."""

    recorded_balance_pence: int
    actual_balance_pence: int
    difference_pence: int
    agrees: bool
    #: What would close the gap, named as one of the two acts that exist.
    put_right_by: str | None


def reconcile(session: Session, actual_balance_pence: int) -> Reconciliation:
    """Compare the recorded balance with what the account really holds.

    This deliberately records nothing, and that is the whole design rather
    than an omission.

    The ledger is append-only and has four entry types, none of which means
    "the books were wrong". Inventing a fifth to paper over a difference would
    make the balance agree while destroying the only information the
    difference carries: that something happened to the account which nobody
    wrote down. The monthly match is computed from the lowest balance a month
    reached, so an unexplained adjustment silently moves money the scheme is
    about to pay a match on.

    A difference has a cause, and the cause is one of two things this app
    already has an act for. Money missing is a withdrawal nobody logged. Money
    extra is a deposit or a gift that never reached the ledger — and there is
    no endpoint for that yet, which this says plainly rather than pretending
    otherwise.

    Two callers: the open check on the parent's Savings panel, and the bank
    holder's settling of the savings match, which checks the balance after
    the transfer (app.routers.savings_match).
    """
    recorded = current_balance(session)
    difference = actual_balance_pence - recorded

    if difference == 0:
        put_right_by = None
    elif difference < 0:
        put_right_by = (
            f"{abs(difference)}p has left the account without being logged."
            " Record it as a withdrawal, with what it went on."
        )
    else:
        put_right_by = (
            f"{difference}p is in the account that the ledger does not know"
            " about. Nothing here records money arriving from outside a"
            " payday, so this needs deciding rather than entering."
        )

    return Reconciliation(
        recorded_balance_pence=recorded,
        actual_balance_pence=actual_balance_pence,
        difference_pence=difference,
        agrees=difference == 0,
        put_right_by=put_right_by,
    )


def has_entries(session: Session) -> bool:
    return session.query(func.count(SavingsEntry.id)).scalar() > 0


def record_opening_balance(
    session: Session, *, amount_pence: int, occurred_on: date, reason: str | None = None
) -> SavingsEntry:
    """What was already in the account on the day this started.

    A one-off. It has to be the first entry the ledger ever sees, because
    everything after it is a movement from a balance, and inserting a starting
    point after the fact would make every balance recorded before it wrong.
    """
    if amount_pence < 0:
        raise SavingsError("An opening balance cannot be negative.")
    if has_entries(session):
        raise SavingsError(
            "The savings ledger already has entries; an opening balance is"
            " recorded once, before anything else."
        )

    entry = SavingsEntry(
        entry_type=SavingsType.OPENING_BALANCE,
        amount_pence=amount_pence,
        balance_after_pence=amount_pence,
        occurred_on=occurred_on,
        reason=reason or "Opening balance",
    )
    session.add(entry)
    session.flush()
    return entry


def record_deposit(
    session: Session,
    *,
    amount_pence: int,
    occurred_on: date,
    week_id: int | None = None,
    reason: str | None = None,
    posted_by: str | None = None,
) -> SavingsEntry:
    """Money going into the account: kept back from a payday, or standalone.

    posted_by names who a standalone deposit was posted by — see
    app.services.savings_deposits, the only caller that ever passes it. A
    payday's own deposit names nobody; it belongs to the week it split from.
    """
    if amount_pence <= 0:
        raise SavingsError("A deposit is money going in; it must be positive.")

    entry = SavingsEntry(
        entry_type=SavingsType.DEPOSIT,
        amount_pence=amount_pence,
        balance_after_pence=current_balance(session) + amount_pence,
        occurred_on=occurred_on,
        week_id=week_id,
        reason=reason,
        posted_by=posted_by,
    )
    session.add(entry)
    session.flush()
    return entry


def record_withdrawal(
    session: Session, *, amount_pence: int, occurred_on: date, reason: str
) -> SavingsEntry:
    """Money taken out. Stored negative, and the only kind of entry that is.

    This is not a deduction from anything the child earned — nothing is ever
    taken away from him. It is his own money leaving his own account, and the
    monthly match needs to see it happen, which is the other reason the ledger
    exists before the match does.
    """
    if amount_pence <= 0:
        raise SavingsError("Give the amount withdrawn as a positive number.")

    balance = current_balance(session)
    if amount_pence > balance:
        raise SavingsError(
            f"There is {balance}p in the account; {amount_pence}p cannot come out."
        )

    entry = SavingsEntry(
        entry_type=SavingsType.WITHDRAWAL,
        amount_pence=-amount_pence,
        balance_after_pence=balance - amount_pence,
        occurred_on=occurred_on,
        reason=reason,
    )
    session.add(entry)
    session.flush()
    return entry


def record_reversal(
    session: Session, *, amount_pence: int, occurred_on: date, week_id: int, reason: str
) -> SavingsEntry:
    """Undo a deposit that should not have counted. Stored negative.

    Not a withdrawal: the child did not choose to take this out, and calling
    it one would blur two facts a reader needs to tell apart a year later —
    a withdrawal is his own choice, a reversal is a reopened week's payment
    being unwound. The original deposit row is never touched; this is a new
    row, exactly like every other correction this ledger ever makes.

    Refuses to take the balance below zero — there is nowhere for the money
    to come from, the same reason a withdrawal refuses. That can genuinely
    happen: the deposit this is meant to undo may already have been spent
    elsewhere in the account. When it does, the reopen itself is refused
    rather than left to corrupt the balance, and a parent has to settle the
    account by hand first.
    """
    if amount_pence <= 0:
        raise SavingsError("A reversal undoes a positive deposit; give a positive amount.")

    balance = current_balance(session)
    if amount_pence > balance:
        raise SavingsError(
            f"There is {balance}p in the account; {amount_pence}p of it was"
            " deposited from this week's payment but cannot be reversed —"
            " some of it has already been spent."
        )

    entry = SavingsEntry(
        entry_type=SavingsType.REVERSAL,
        amount_pence=-amount_pence,
        balance_after_pence=balance - amount_pence,
        occurred_on=occurred_on,
        week_id=week_id,
        reason=reason,
    )
    session.add(entry)
    session.flush()
    return entry


def record_match(
    session: Session, *, amount_pence: int, occurred_on: date, reason: str | None = None
) -> SavingsEntry:
    """The monthly match, once a month settles. Written by
    app.services.savings_match.settle, never called directly by a router.

    Unlike a deposit, zero is allowed: a month whose low was nil, or whose
    rate applied to nil, still closes on that figure, and the ledger records
    it plainly rather than skipping a row for it — the same choice
    settlement.settle makes when a week's total comes to nothing.
    """
    if amount_pence < 0:
        raise SavingsError("A match cannot be negative.")

    entry = SavingsEntry(
        entry_type=SavingsType.MATCH,
        amount_pence=amount_pence,
        balance_after_pence=current_balance(session) + amount_pence,
        occurred_on=occurred_on,
        reason=reason,
    )
    session.add(entry)
    session.flush()
    return entry


def history(session: Session) -> list[SavingsEntry]:
    return session.query(SavingsEntry).order_by(SavingsEntry.id).all()
