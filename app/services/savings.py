"""The savings ledger.

Nothing in the app computes a monthly match yet. The ledger is here anyway,
from the first payday, because the match rewards money left alone and that can
only be worked out from a balance history nobody kept at the time. Deferring
the feature is a choice about when to build something; deferring the record is
a choice to make the feature impossible when it arrives. The first is
reversible and the second is not.

Every entry carries the balance after it. That is a running total written once
into a row that cannot be edited — not a mutable field that could drift out of
step with the entries that produced it.
"""

from __future__ import annotations

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
) -> SavingsEntry:
    """Money kept back from a payday and put into the account."""
    if amount_pence <= 0:
        raise SavingsError("A deposit is money going in; it must be positive.")

    entry = SavingsEntry(
        entry_type=SavingsType.DEPOSIT,
        amount_pence=amount_pence,
        balance_after_pence=current_balance(session) + amount_pence,
        occurred_on=occurred_on,
        week_id=week_id,
        reason=reason,
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


def history(session: Session) -> list[SavingsEntry]:
    return session.query(SavingsEntry).order_by(SavingsEntry.id).all()
