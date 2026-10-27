"""The monthly savings match.

Reading a proposal needs no PIN — it changes nothing, the same as a week's
proposal. Settling does: it is the act that moves money, and closes the
month forever.

Settling is also the one act restricted to a single parent. The match is
paid into the bank by the parent who holds the account (app.config,
BANK_HOLDER), outside this app, and settling records that it was — so only
that parent's PIN may settle, along with the bank balance checked as part of
it. Any other parent's correct PIN is refused with a plain reason, and is not
a failed PIN attempt: the PIN was right, the act was not theirs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.config import get_settings as _settings
from app.routers.weeks import ReconciliationView
from app.services import savings, savings_match
from app.services.savings_match import (
    MonthAlreadySettled,
    MonthlyMatchProposal,
    MonthNotOver,
    NoSavingsYet,
    ProposalChanged,
)

router = APIRouter(prefix="/api/savings/match", tags=["savings"])


class MonthlyMatchProposalView(BaseModel):
    period_start: str
    period_end: str
    balance_low_pence: int
    had_withdrawal: bool
    rate_percent: int
    cap_pence: int
    match_pence: int
    #: False while the month is still in progress — the figures above are a
    #: preview and will keep moving. True once there is nothing left for
    #: them to do but be settled.
    month_has_ended: bool
    clean_months_in_a_row: int

    @classmethod
    def of(cls, proposal: MonthlyMatchProposal) -> MonthlyMatchProposalView:
        return cls(
            period_start=proposal.period_start.isoformat(),
            period_end=proposal.period_end.isoformat(),
            balance_low_pence=proposal.balance_low_pence,
            had_withdrawal=proposal.had_withdrawal,
            rate_percent=proposal.rate_percent,
            cap_pence=proposal.cap_pence,
            match_pence=proposal.match_pence,
            month_has_ended=proposal.month_has_ended,
            clean_months_in_a_row=proposal.clean_months_in_a_row,
        )


class SettledMonthView(BaseModel):
    id: int
    period_start: str
    period_end: str
    balance_low_pence: int
    had_withdrawal: bool
    rate_percent: int
    cap_pence: int
    match_pence: int
    settled_by: str
    settled_at: str

    @classmethod
    def of(cls, row) -> SettledMonthView:
        return cls(
            id=row.id,
            period_start=row.period_start.isoformat(),
            period_end=row.period_end.isoformat(),
            balance_low_pence=row.balance_low_pence,
            had_withdrawal=row.had_withdrawal,
            rate_percent=row.rate_percent,
            cap_pence=row.cap_pence,
            match_pence=row.match_pence,
            settled_by=row.settled_by,
            settled_at=row.settled_at.isoformat(),
        )


class DueMonthView(BaseModel):
    """An ended month waiting for a parent to settle it, and what it pays."""

    period_start: str
    period_end: str
    match_pence: int

    @classmethod
    def of(cls, proposal: MonthlyMatchProposal) -> DueMonthView:
        return cls(
            period_start=proposal.period_start.isoformat(),
            period_end=proposal.period_end.isoformat(),
            match_pence=proposal.match_pence,
        )


class SettleMonthRequest(AuthorisedRequest):
    agreed_match_pence: int = Field(ge=0)
    #: What the bank account holds after the transfer, if the bank holder
    #: gave it: checked against the books once the match is on them.
    #: Optional; never recorded (app.services.savings.reconcile).
    bank_balance_pence: int | None = Field(default=None, ge=0)


class SettledMonthResultView(SettledMonthView):
    """The month just settled, and the bank balance checked with it, if one
    was given."""

    reconciliation: ReconciliationView | None = None


def _proposal(session: Session) -> MonthlyMatchProposal:
    try:
        return savings_match.propose(session, get_settings().tzinfo)
    except NoSavingsYet as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None


@router.get("", response_model=list[SettledMonthView])
def list_settled_months(session: Session = Depends(get_session)) -> list[SettledMonthView]:
    """Every month settled so far, oldest first."""
    return [SettledMonthView.of(row) for row in savings_match.settled_months(session)]


@router.get("/proposal", response_model=MonthlyMatchProposalView)
def get_proposal(session: Session = Depends(get_session)) -> MonthlyMatchProposalView:
    """What the next unsettled month is worth, whether or not it has ended
    yet — see `month_has_ended`. Applies nothing, needs no PIN.

    409 only when the savings ledger has no entries at all to match against.
    """
    return MonthlyMatchProposalView.of(_proposal(session))


@router.get("/due", response_model=list[DueMonthView])
def list_due_months(session: Session = Depends(get_session)) -> list[DueMonthView]:
    """Every ended, unsettled month that would pay something, oldest first.

    For the wall, the same way it reads the weeks still owed: no PIN, and it
    settles nothing — a due month stays on this list until a parent settles
    it. Empty when there is nothing saved to match yet.
    """
    tz = get_settings().tzinfo
    return [DueMonthView.of(month) for month in savings_match.due_months(session, tz)]


@router.post("/settle", response_model=SettledMonthResultView)
def settle_month(
    request: Request,
    body: SettleMonthRequest,
    session: Session = Depends(get_session),
) -> SettledMonthResultView:
    """Close the next unsettled month on a figure the bank holder has read
    and agreed, after paying it into the bank.

    Refused with 403 for any parent but the bank holder — after the PIN is
    verified, so it is not counted as a failed attempt. Refused with 409 if
    that month has not finished yet — propose() will happily preview it, but
    nothing may be settled on figures still able to move.
    """
    authorisation = authorise(request, body)
    if not authorisation.bank_holder:
        holder = _settings().bank_holder.name
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only {holder} can settle the interest, because it is paid into the bank.",
        )

    try:
        proposal = _proposal(session)
        row = savings_match.settle(
            session, proposal, authorisation, agreed_match_pence=body.agreed_match_pence
        )
        session.commit()
    except (MonthNotOver, ProposalChanged, MonthAlreadySettled) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(row)
    checked = (
        None
        if body.bank_balance_pence is None
        else ReconciliationView.of(savings.reconcile(session, body.bank_balance_pence))
    )
    return SettledMonthResultView(**SettledMonthView.of(row).model_dump(), reconciliation=checked)
