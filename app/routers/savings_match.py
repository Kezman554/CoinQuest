"""The monthly savings match.

Reading a proposal needs no PIN — it changes nothing, the same as a week's
proposal. Settling does: it is the act that moves money, and closes the
month forever.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services import savings_match
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


class SettleMonthRequest(AuthorisedRequest):
    agreed_match_pence: int = Field(ge=0)


def _proposal(session: Session) -> MonthlyMatchProposal:
    try:
        return savings_match.propose(session, get_settings().tzinfo)
    except (NoSavingsYet, MonthNotOver) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None


@router.get("", response_model=list[SettledMonthView])
def list_settled_months(session: Session = Depends(get_session)) -> list[SettledMonthView]:
    """Every month settled so far, oldest first."""
    return [SettledMonthView.of(row) for row in savings_match.settled_months(session)]


@router.get("/proposal", response_model=MonthlyMatchProposalView)
def get_proposal(session: Session = Depends(get_session)) -> MonthlyMatchProposalView:
    """What the next unsettled month is on track to match. Applies nothing.

    409 when that month has not finished yet, or the savings ledger has no
    entries at all to match against.
    """
    return MonthlyMatchProposalView.of(_proposal(session))


@router.post("/settle", response_model=SettledMonthView)
def settle_month(
    request: Request,
    body: SettleMonthRequest,
    session: Session = Depends(get_session),
) -> SettledMonthView:
    """Close the next unsettled month on a figure a parent has read and agreed."""
    authorisation = authorise(request, body)

    try:
        proposal = _proposal(session)
        row = savings_match.settle(
            session, proposal, authorisation, agreed_match_pence=body.agreed_match_pence
        )
        session.commit()
    except (ProposalChanged, MonthAlreadySettled) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(row)
    return SettledMonthView.of(row)
