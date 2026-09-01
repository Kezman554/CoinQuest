"""A savings deposit posted outside payday, and the two shapes that takes.

Oliver posts a deposit the same way he claims a chore: no credential, and it
changes nothing until a parent rules on it. `submit` creates the pending row;
`confirm` writes the real ledger entry a parent agreed to and links back to
it; `reject` closes the request without the ledger ever hearing about it.

A parent posts a deposit directly instead of through that queue — the PIN
already proves the party, so there is nothing left to wait for.
`record_parent_deposit` writes straight to the ledger and creates no pending
row at all.

Both routes call app.services.savings.record_deposit for the actual write,
so a confirmed or parent-posted deposit raises the balance and the current
month's low exactly like any other deposit already does. Neither resets the
savings-match ladder or the clean-months streak: that logic (see
app.services.savings_match) keys only on SavingsType.WITHDRAWAL, which
nothing here ever writes.

Who may post what is read fresh from app.config on every call, not cached
here — a name added to PARENT_NAMES takes effect the moment the process
picks up the new environment, with no code of its own to update.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import DepositRequestState
from app.models.ledgers import SavingsEntry
from app.models.savings_deposits import PendingSavingsDeposit
from app.services import savings
from app.services.authorisation import Authorisation


class DepositRequestError(Exception):
    """Something a standalone deposit, or a decision on one, will not accept."""


def child_name() -> str:
    return get_settings().child_name


def parent_names() -> list[str]:
    return list(get_settings().parent_names)


def is_child(name: str) -> bool:
    return name == child_name()


def is_parent(name: str) -> bool:
    return name in get_settings().parent_names


def _note(note: str) -> str:
    note = note.strip()
    if not note:
        raise DepositRequestError("A deposit needs a note saying what it is.")
    return note


def _amount(amount_pence: int) -> int:
    if amount_pence <= 0:
        raise DepositRequestError("A deposit is money going in; it must be positive.")
    return amount_pence


def submit(
    session: Session,
    *,
    amount_pence: int,
    note: str,
    posted_by: str,
    occurred_on: date,
) -> PendingSavingsDeposit:
    """Oliver proposes a deposit. Unauthenticated, and moves no money yet.

    Refuses anything posted as other than the child: waiting for a parent is
    what this identity means here, and a parent's own deposit does not wait
    — see record_parent_deposit, the other door into the ledger.
    """
    if not is_child(posted_by):
        raise DepositRequestError(
            f"Only {child_name()} posts a deposit that waits for a parent;"
            " a parent posts one directly instead."
        )

    request = PendingSavingsDeposit(
        amount_pence=_amount(amount_pence),
        note=_note(note),
        posted_by=posted_by,
        occurred_on=occurred_on,
    )
    session.add(request)
    session.flush()
    return request


def pending(session: Session) -> list[PendingSavingsDeposit]:
    """Every deposit still waiting on a parent, oldest first."""
    return (
        session.query(PendingSavingsDeposit)
        .filter(PendingSavingsDeposit.state == DepositRequestState.PENDING)
        .order_by(PendingSavingsDeposit.id)
        .all()
    )


def _load_pending(session: Session, request_id: int) -> PendingSavingsDeposit:
    request = session.get(PendingSavingsDeposit, request_id)
    if request is None:
        raise DepositRequestError(f"No deposit request {request_id}.")
    if request.state is not DepositRequestState.PENDING:
        raise DepositRequestError(f"That deposit is already {request.state.value}.")
    return request


def confirm(
    session: Session, *, request_id: int, authorisation: Authorisation
) -> PendingSavingsDeposit:
    """A parent agrees a pending deposit: it lands in the ledger, for real.

    Loaded and checked fresh rather than trusted from a caller — the same
    defence settlement.settle and savings_match.settle both apply — so two
    requests racing to rule on the same pending deposit cannot both succeed.
    """
    request = _load_pending(session, request_id)

    entry = savings.record_deposit(
        session,
        amount_pence=request.amount_pence,
        occurred_on=request.occurred_on,
        reason=request.note,
        posted_by=request.posted_by,
    )

    request.state = DepositRequestState.CONFIRMED
    request.decided_at = authorisation.at
    request.decided_by = authorisation.party
    request.savings_entry_id = entry.id
    session.flush()
    return request


def reject(
    session: Session, *, request_id: int, authorisation: Authorisation
) -> PendingSavingsDeposit:
    """A parent declines a pending deposit. The ledger never hears about it."""
    request = _load_pending(session, request_id)

    request.state = DepositRequestState.REJECTED
    request.decided_at = authorisation.at
    request.decided_by = authorisation.party
    session.flush()
    return request


def record_parent_deposit(
    session: Session,
    *,
    amount_pence: int,
    note: str,
    posted_by: str,
    occurred_on: date,
) -> SavingsEntry:
    """A parent posts a deposit directly. Already authorised; nothing waits.

    Refuses anything posted as the child — that identity is what has to wait
    for a parent, see submit(). This is also how the opening balance is
    meant to be entered at go-live: a parent, a note like "opening balance",
    posted the same way any later deposit will be.
    """
    if not is_parent(posted_by):
        raise DepositRequestError(f"{posted_by!r} is not a recognised parent name.")

    return savings.record_deposit(
        session,
        amount_pence=_amount(amount_pence),
        occurred_on=occurred_on,
        reason=_note(note),
        posted_by=posted_by,
    )
