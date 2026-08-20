"""Weeks: what one is on track to pay, and closing it.

Reading a proposal needs no credential — the child is meant to see where he
stands without asking, and a proposal changes nothing. Closing a week does,
and closing one is permanent, so both settling and voiding carry the PIN and
are refused server-side without it.

Settling submits the figure the parent read. If the week is no longer worth
that, the request is refused rather than quietly settled on a different
number: a stored amount nobody agreed to is the one mistake this app cannot
correct afterwards.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import WeekStatus
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services import settlement
from app.services.settlement import NotOpen, ProposalChanged

router = APIRouter(prefix="/api/weeks", tags=["weeks"])


# --- What goes out ---------------------------------------------------------


class LineView(BaseModel):
    chore_name: str
    category: str
    unit_amount_pence: int
    quantity: int
    amount_pence: int
    note: str | None = None


class RecoveryView(BaseModel):
    miss_name: str
    spent_name: str
    forgone_pence: int


class ProposalView(BaseModel):
    """What the week is on track to pay. Nothing has been applied."""

    week_id: int
    start_date: str
    end_date: str
    status: str
    base_pence: int
    chore_pay_at_stake_pence: int
    chore_pay_pence: int
    chore_pay_awarded: bool
    bonus_pence: int
    reward_pence: int
    total_pence: int
    misses: int
    misses_outstanding: int
    recoveries: list[RecoveryView]
    recovery_cap: int
    days_waived: int
    lines: list[LineView]

    @classmethod
    def of(cls, proposal: settlement.Proposal) -> ProposalView:
        return cls(
            week_id=proposal.week_id,
            start_date=proposal.start_date.isoformat(),
            end_date=proposal.end_date.isoformat(),
            status=WeekStatus.OPEN.value,
            base_pence=proposal.base_pence,
            chore_pay_at_stake_pence=proposal.chore_pay_at_stake_pence,
            chore_pay_pence=proposal.chore_pay_pence,
            chore_pay_awarded=proposal.chore_pay_awarded,
            bonus_pence=proposal.bonus_pence,
            reward_pence=proposal.reward_pence,
            total_pence=proposal.total_pence,
            misses=len(proposal.misses),
            misses_outstanding=proposal.misses_outstanding,
            recoveries=[
                RecoveryView(
                    miss_name=recovery.miss_name,
                    spent_name=recovery.spent_name,
                    forgone_pence=recovery.forgone_pence,
                )
                for recovery in proposal.recoveries
            ],
            recovery_cap=proposal.cap,
            days_waived=proposal.days_waived,
            lines=[
                LineView(
                    chore_name=line.chore_name,
                    category=line.category.value,
                    unit_amount_pence=line.unit_amount_pence,
                    quantity=line.quantity,
                    amount_pence=line.amount_pence,
                    note=line.note,
                )
                for line in proposal.lines
            ],
        )


class SettledWeekView(BaseModel):
    """A closed week, read from its own stored columns."""

    week_id: int
    start_date: str
    end_date: str
    status: str
    base_pence: int | None
    chore_pay_pence: int | None
    bonus_pence: int | None
    reward_pence: int | None
    total_pence: int | None
    closed_at: str | None
    void_reason: str | None
    paid_at: str | None
    deposited_pence: int | None
    lines: list[LineView]

    @classmethod
    def of(cls, week: Week) -> SettledWeekView:
        figures = settlement.stored_figures(week)
        return cls(
            week_id=week.id,
            start_date=week.start_date.isoformat(),
            end_date=week.end_date.isoformat(),
            status=figures["status"],
            base_pence=figures["base_pence"],
            chore_pay_pence=figures["chore_pay_pence"],
            bonus_pence=figures["bonus_pence"],
            reward_pence=figures["reward_pence"],
            total_pence=figures["total_pence"],
            closed_at=figures["closed_at"],
            void_reason=figures["void_reason"],
            paid_at=week.paid_at.isoformat() if week.paid_at else None,
            deposited_pence=week.deposited_pence,
            lines=[
                LineView(
                    chore_name=line.chore_name,
                    category=line.category.value,
                    unit_amount_pence=line.unit_amount_pence,
                    quantity=line.quantity,
                    amount_pence=line.amount_pence,
                    note=line.note,
                )
                for line in week.settlement_lines
            ],
        )


class WeekSummary(BaseModel):
    week_id: int
    start_date: str
    end_date: str
    status: str
    total_pence: int | None


# --- What comes in ---------------------------------------------------------


class SettleRequest(AuthorisedRequest):
    """Explicit agreement to a figure the parent has read."""

    agreed_total_pence: int = Field(ge=0)


class VoidRequest(AuthorisedRequest):
    reason: str = Field(min_length=1)


# --- Helpers ---------------------------------------------------------------


def _load(session: Session, week_id: int) -> Week:
    week = session.get(Week, week_id)
    if week is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No week {week_id}."
        )
    return week


def _proposal(session: Session, week: Week) -> settlement.Proposal:
    try:
        return settlement.propose(session, week, get_settings().tzinfo)
    except NotOpen as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None


# --- Endpoints -------------------------------------------------------------


@router.get("", response_model=list[WeekSummary])
def list_weeks(session: Session = Depends(get_session)) -> list[WeekSummary]:
    """Every week, oldest first. Several may be open at once."""
    weeks = session.query(Week).order_by(Week.start_date).all()
    return [
        WeekSummary(
            week_id=week.id,
            start_date=week.start_date.isoformat(),
            end_date=week.end_date.isoformat(),
            status=week.status.value,
            total_pence=week.settled_total_pence,
        )
        for week in weeks
    ]


@router.get("/{week_id}/proposal", response_model=ProposalView)
def get_proposal(
    week_id: int, session: Session = Depends(get_session)
) -> ProposalView:
    """What this week is on track to pay. Applies nothing, needs no PIN.

    Refused for a closed week: a closed week is read from its own figures at
    /api/weeks/{id}, never recomputed from today's chores.
    """
    return ProposalView.of(_proposal(session, _load(session, week_id)))


@router.get("/{week_id}", response_model=SettledWeekView | ProposalView)
def get_week(week_id: int, session: Session = Depends(get_session)):
    """A week. Stored figures if it is closed, a proposal if it is open."""
    week = _load(session, week_id)
    if week.status is WeekStatus.OPEN:
        return ProposalView.of(_proposal(session, week))
    return SettledWeekView.of(week)


@router.post("/{week_id}/settle", response_model=SettledWeekView)
def settle_week(
    week_id: int,
    body: SettleRequest,
    session: Session = Depends(get_session),
) -> SettledWeekView:
    """Close a week on figures the parent has read and agreed."""
    authorisation = authorise(body)
    week = _load(session, week_id)

    try:
        proposal = _proposal(session, week)
        settlement.settle(
            session,
            week,
            proposal,
            authorisation,
            agreed_total_pence=body.agreed_total_pence,
        )
        session.commit()
    except ProposalChanged as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(week)
    return SettledWeekView.of(week)


@router.post("/{week_id}/void", response_model=SettledWeekView)
def void_week(
    week_id: int,
    body: VoidRequest,
    session: Session = Depends(get_session),
) -> SettledWeekView:
    """Close a week paying nothing, keeping the record of what was done."""
    authorisation = authorise(body)
    week = _load(session, week_id)

    try:
        settlement.void(
            session, week, authorisation, reason=body.reason, tz=get_settings().tzinfo
        )
        session.commit()
    except NotOpen as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    session.refresh(week)
    return SettledWeekView.of(week)
