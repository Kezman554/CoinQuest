"""A savings deposit made outside payday.

Two doors, two credentials, mirroring app/routers/claims.py's own split
rather than one endpoint branching on who the body claims to be:

  Submitting (POST "") is unauthenticated, like a chore claim — it can only
  ever create a pending request for the child's own name, refused for
  anyone else's. Confirming or rejecting one is what a parent does, and
  both carry the PIN.

  A parent posting directly (POST "/parent") is its own endpoint, carries
  the PIN, and refuses the child's own name — that identity is what has to
  wait, and this is not the door that waits.

A request typed straight at the API meets exactly these same checks,
whatever the frontend chose to show — see claims.py's own note on this.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ledgers import SavingsEntry
from app.models.savings_deposits import PendingSavingsDeposit
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services import savings_deposits as deposits
from app.services.calendar import today
from app.services.savings_deposits import DepositRequestError

router = APIRouter(prefix="/api/savings/deposits", tags=["savings"])


# --- What goes out -----------------------------------------------------------


class DepositorsView(BaseModel):
    """The fixed list this deposit's posted_by may be chosen from."""

    child_name: str
    parent_names: list[str]


class DepositRequestView(BaseModel):
    id: int
    amount_pence: int
    note: str
    posted_by: str
    occurred_on: str
    state: str
    submitted_at: str
    decided_at: str | None
    decided_by: str | None

    @classmethod
    def of(cls, request: PendingSavingsDeposit) -> DepositRequestView:
        return cls(
            id=request.id,
            amount_pence=request.amount_pence,
            note=request.note,
            posted_by=request.posted_by,
            occurred_on=request.occurred_on.isoformat(),
            state=request.state.value,
            submitted_at=request.submitted_at.isoformat(),
            decided_at=request.decided_at.isoformat() if request.decided_at else None,
            decided_by=request.decided_by,
        )


class SavingsEntryView(BaseModel):
    id: int
    entry_type: str
    amount_pence: int
    balance_after_pence: int
    occurred_on: str
    reason: str | None
    posted_by: str | None

    @classmethod
    def of(cls, entry: SavingsEntry) -> SavingsEntryView:
        return cls(
            id=entry.id,
            entry_type=entry.entry_type.value,
            amount_pence=entry.amount_pence,
            balance_after_pence=entry.balance_after_pence,
            occurred_on=entry.occurred_on.isoformat(),
            reason=entry.reason,
            posted_by=entry.posted_by,
        )


# --- What comes in ------------------------------------------------------------


class SubmitDepositRequest(BaseModel):
    """Oliver proposing a deposit. No credential, by design — see claim()."""

    amount_pence: int = Field(gt=0)
    note: str = Field(min_length=1)
    posted_by: str
    occurred_on: date | None = None


class DecideDepositRequest(AuthorisedRequest):
    """A parent ruling on a pending deposit — confirm or reject, either way
    carries the PIN."""


class ParentDepositRequest(AuthorisedRequest):
    """A parent posting a deposit directly. Authorised at submission; there
    is no pending step behind it."""

    amount_pence: int = Field(gt=0)
    note: str = Field(min_length=1)
    posted_by: str
    occurred_on: date | None = None


# --- Shared -------------------------------------------------------------------


def _load(session: Session, request_id: int) -> PendingSavingsDeposit:
    request = session.get(PendingSavingsDeposit, request_id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No deposit request {request_id}.",
        )
    return request


# --- Reading -------------------------------------------------------------------


@router.get("/depositors", response_model=DepositorsView)
def depositors() -> DepositorsView:
    """The fixed list a deposit's posted_by may be chosen from. Never a
    schema question — see app.config.parent_names."""
    settings = get_settings()
    return DepositorsView(child_name=settings.child_name, parent_names=settings.parent_names)


@router.get("/pending", response_model=list[DepositRequestView])
def pending(session: Session = Depends(get_session)) -> list[DepositRequestView]:
    """Every deposit still waiting on a parent, oldest first. No PIN — reading
    what is waiting is not the act that moves money."""
    return [DepositRequestView.of(request) for request in deposits.pending(session)]


# --- Oliver's endpoint ---------------------------------------------------------


@router.post("", response_model=DepositRequestView, status_code=status.HTTP_201_CREATED)
def submit(
    body: SubmitDepositRequest, session: Session = Depends(get_session)
) -> DepositRequestView:
    """Propose a deposit. Pending until a parent confirms it; changes no
    balance on its own. Refused for anyone posted as other than the child —
    see /parent for the door a parent uses instead."""
    day = body.occurred_on or today(get_settings().tzinfo)

    try:
        request = deposits.submit(
            session,
            amount_pence=body.amount_pence,
            note=body.note,
            posted_by=body.posted_by,
            occurred_on=day,
        )
        session.commit()
    except DepositRequestError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(request)
    return DepositRequestView.of(request)


# --- The parent's endpoints -----------------------------------------------------


@router.post("/{request_id}/confirm", response_model=DepositRequestView)
def confirm(
    request_id: int,
    request: Request,
    body: DecideDepositRequest,
    session: Session = Depends(get_session),
) -> DepositRequestView:
    """Agree a pending deposit. Writes the real ledger entry and closes the
    request on it — refused if it is not still pending, whatever this
    screen shows."""
    authorisation = authorise(request, body)
    _load(session, request_id)

    try:
        deposit_request = deposits.confirm(
            session, request_id=request_id, authorisation=authorisation
        )
        session.commit()
    except DepositRequestError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(deposit_request)
    return DepositRequestView.of(deposit_request)


@router.post("/{request_id}/reject", response_model=DepositRequestView)
def reject(
    request_id: int,
    request: Request,
    body: DecideDepositRequest,
    session: Session = Depends(get_session),
) -> DepositRequestView:
    """Decline a pending deposit. The ledger never hears about it."""
    authorisation = authorise(request, body)
    _load(session, request_id)

    try:
        deposit_request = deposits.reject(
            session, request_id=request_id, authorisation=authorisation
        )
        session.commit()
    except DepositRequestError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(deposit_request)
    return DepositRequestView.of(deposit_request)


@router.post(
    "/parent", response_model=SavingsEntryView, status_code=status.HTTP_201_CREATED
)
def record_parent_deposit(
    request: Request,
    body: ParentDepositRequest,
    session: Session = Depends(get_session),
) -> SavingsEntryView:
    """A parent posts a deposit directly. Authorised here, at submission —
    there is no pending step, since a parent's own act is already
    authoritative. This is also how the opening balance is meant to be
    entered at go-live: a note like "opening balance", posted the same way
    any later deposit will be."""
    authorise(request, body)
    day = body.occurred_on or today(get_settings().tzinfo)

    try:
        entry = deposits.record_parent_deposit(
            session,
            amount_pence=body.amount_pence,
            note=body.note,
            posted_by=body.posted_by,
            occurred_on=day,
        )
        session.commit()
    except DepositRequestError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(entry)
    return SavingsEntryView.of(entry)
