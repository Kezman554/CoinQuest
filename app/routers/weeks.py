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

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import WeekStatus
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services import payments, savings, settlement
from app.services.calendar import today
from app.services.payments import PaymentError
from app.services.recovery import InvalidAssignment, SuppliedRecovery
from app.services.savings import SavingsError
from app.services.settlement import NotOpen, ProposalChanged

router = APIRouter(prefix="/api/weeks", tags=["weeks"])

#: Savings sits behind its own prefix but belongs to the same act: an opening
#: balance and a payday deposit are the two ways money reaches the account.
savings_router = APIRouter(prefix="/api/savings", tags=["savings"])


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
    overridden: bool
    optimum_total_pence: int
    foregone_pence: int
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
            overridden=proposal.overridden,
            optimum_total_pence=proposal.optimum_total_pence,
            foregone_pence=proposal.foregone_pence,
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
    overridden_by: str | None
    override_reason: str | None
    optimum_total_pence: int | None
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
            overridden_by=figures["overridden_by"],
            override_reason=figures["override_reason"],
            optimum_total_pence=figures["optimum_total_pence"],
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


class SuppliedRecoveryIn(BaseModel):
    """Spend this chore to cover a miss of that one."""

    spend_definition_id: int
    for_definition_id: int


class OverrideRequest(BaseModel):
    """An assignment of make-goods a parent chose themselves.

    An empty list is a real instruction — recover nothing — and is not the
    same as sending no override at all, which means "use the computed one".
    """

    recoveries: list[SuppliedRecoveryIn]
    reason: str | None = None

    def supplied(self) -> list[SuppliedRecovery]:
        return [
            SuppliedRecovery(
                spend_definition_id=recovery.spend_definition_id,
                for_definition_id=recovery.for_definition_id,
            )
            for recovery in self.recoveries
        ]


class ProposalPreviewRequest(BaseModel):
    """Ask what a week would be worth under an assignment of your own."""

    override: OverrideRequest


class SettleRequest(AuthorisedRequest):
    """Explicit agreement to a figure the parent has read.

    If `override` is given, the figure being agreed is the overridden one —
    the same check applies, against the same proposal the parent was shown.
    """

    agreed_total_pence: int = Field(ge=0)
    override: OverrideRequest | None = None


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


def _proposal(
    session: Session, week: Week, override: OverrideRequest | None = None
) -> settlement.Proposal:
    try:
        return settlement.propose(
            session,
            week,
            get_settings().tzinfo,
            override=override.supplied() if override is not None else None,
        )
    except NotOpen as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except InvalidAssignment as exc:
        # A parent may choose to lose money. They may not choose to break the
        # rules, and the refusal says which rule.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
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


@router.post("/{week_id}/proposal", response_model=ProposalView)
def preview_proposal(
    week_id: int,
    body: ProposalPreviewRequest,
    session: Session = Depends(get_session),
) -> ProposalView:
    """What the week would be worth under an assignment of the parent's own.

    Reading, not writing, so it carries no PIN — and a parent has to be able
    to read a figure before they can agree to it.
    """
    return ProposalView.of(_proposal(session, _load(session, week_id), body.override))


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
    request: Request,
    body: SettleRequest,
    session: Session = Depends(get_session),
) -> SettledWeekView:
    """Close a week on figures the parent has read and agreed."""
    authorisation = authorise(request, body)
    week = _load(session, week_id)

    try:
        proposal = _proposal(session, week, body.override)
        settlement.settle(
            session,
            week,
            proposal,
            authorisation,
            agreed_total_pence=body.agreed_total_pence,
            override_reason=body.override.reason if body.override else None,
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
    request: Request,
    body: VoidRequest,
    session: Session = Depends(get_session),
) -> SettledWeekView:
    """Close a week paying nothing, keeping the record of what was done."""
    authorisation = authorise(request, body)
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


# --- Payday ----------------------------------------------------------------


class OwedView(BaseModel):
    """A closed week and what it comes to, until somebody hands it over."""

    week_id: int
    start_date: str
    end_date: str
    settled_total_pence: int
    reward_pence: int
    owed_pence: int
    is_paid: bool

    @classmethod
    def of(cls, owed: payments.Owed) -> "OwedView":
        return cls(
            week_id=owed.week_id,
            start_date=owed.start_date.isoformat(),
            end_date=owed.end_date.isoformat(),
            settled_total_pence=owed.settled_total_pence,
            reward_pence=owed.reward_pence,
            owed_pence=owed.owed_pence,
            is_paid=owed.is_paid,
        )


class PaymentRequest(AuthorisedRequest):
    """One handing-over, covering one or more settled weeks."""

    week_ids: list[int] = Field(min_length=1)
    deposited_pence: int = Field(ge=0)
    occurred_on: date | None = None


class PaymentView(BaseModel):
    week_ids: list[int]
    paid_pence: int
    deposited_pence: int
    kept_pence: int
    occurred_on: str
    savings_balance_pence: int


@router.get("/owed/outstanding", response_model=list[OwedView])
def list_outstanding(session: Session = Depends(get_session)) -> list[OwedView]:
    """Weeks settled but not yet paid. Reading needs no PIN."""
    return [OwedView.of(owed) for owed in payments.outstanding(session)]


@router.post("/payments", response_model=PaymentView)
def record_payment(
    request: Request,
    body: PaymentRequest,
    session: Session = Depends(get_session),
) -> PaymentView:
    """Mark weeks paid, and bank what the child chose to keep back.

    A separate act from settling, and separately authorised: agreeing what a
    week is worth and handing the money over are two different statements, and
    days apart in practice.
    """
    authorisation = authorise(request, body)
    weeks = [_load(session, week_id) for week_id in body.week_ids]
    day = body.occurred_on or today(get_settings().tzinfo)

    try:
        payment = payments.pay(
            session,
            weeks,
            authorisation,
            deposited_pence=body.deposited_pence,
            occurred_on=day,
        )
        session.commit()
    except (PaymentError, SavingsError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    return PaymentView(
        week_ids=list(payment.week_ids),
        paid_pence=payment.paid_pence,
        deposited_pence=payment.deposited_pence,
        kept_pence=payment.kept_pence,
        occurred_on=payment.occurred_on.isoformat(),
        savings_balance_pence=payment.balance_after_pence,
    )


# --- The savings ledger ----------------------------------------------------


class OpeningBalanceRequest(AuthorisedRequest):
    amount_pence: int = Field(ge=0)
    occurred_on: date | None = None


class SavingsEntryView(BaseModel):
    id: int
    entry_type: str
    amount_pence: int
    balance_after_pence: int
    occurred_on: str
    week_id: int | None
    reason: str | None


class SavingsView(BaseModel):
    balance_pence: int
    entries: list[SavingsEntryView]


def _entry_view(entry) -> SavingsEntryView:
    return SavingsEntryView(
        id=entry.id,
        entry_type=entry.entry_type.value,
        amount_pence=entry.amount_pence,
        balance_after_pence=entry.balance_after_pence,
        occurred_on=entry.occurred_on.isoformat(),
        week_id=entry.week_id,
        reason=entry.reason,
    )


@savings_router.get("", response_model=SavingsView)
def get_savings(session: Session = Depends(get_session)) -> SavingsView:
    """The ledger, and the balance it comes to.

    Nothing computes a match from this yet. The record is kept from the first
    payday regardless, because the match rewards money left alone and that
    cannot be reconstructed later from figures nobody wrote down.
    """
    return SavingsView(
        balance_pence=savings.current_balance(session),
        entries=[_entry_view(entry) for entry in savings.history(session)],
    )


@savings_router.post(
    "/opening-balance", response_model=SavingsEntryView, status_code=status.HTTP_201_CREATED
)
def record_opening_balance(
    request: Request,
    body: OpeningBalanceRequest,
    session: Session = Depends(get_session),
) -> SavingsEntryView:
    """What was already in the account on the day this started. Once only."""
    authorise(request, body)
    day = body.occurred_on or today(get_settings().tzinfo)

    try:
        entry = savings.record_opening_balance(
            session, amount_pence=body.amount_pence, occurred_on=day
        )
        session.commit()
    except SavingsError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    return _entry_view(entry)
