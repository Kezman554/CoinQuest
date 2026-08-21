"""The parent's surface: the queue, and what agreeing to it would do.

Reading needs no credential, here as everywhere. The preview is the interesting
case: it writes, and then throws the write away, and it still carries no PIN.
That is deliberate and it is safe for one reason — the savepoint is rolled back
before the request returns, whether it succeeded or not, so nothing a caller
sends can leave a mark. What it exposes is what a proposal already exposes:
what a week would be worth. The PIN guards the act, not the arithmetic.

Confirming for real is `POST /api/claims/review`, which carries the PIN, is one
transaction, and is where the batch actually happens.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.base import utcnow
from app.routers.dependencies import get_session
from app.services import parent
from app.services.review import Decision, ReviewError
from app.services.settlement import NotOpen

router = APIRouter(prefix="/api/parent", tags=["parent"])


# --- What goes out ---------------------------------------------------------


class PendingView(BaseModel):
    instance_id: int
    definition_id: int
    name: str
    category: str
    cadence: str
    amount_pence: int
    sequence: int
    due_date: str | None
    week_id: int
    week_start_date: str
    claimed_at: str | None
    rejection_count: int


class FiguresView(BaseModel):
    misses: int
    misses_outstanding: int
    recoveries: list[list[str]]
    chore_pay_awarded: bool
    chore_pay_at_stake_pence: int
    chore_pay_pence: int
    bonus_pence: int
    reward_pence: int
    total_pence: int

    @classmethod
    def of(cls, figures: parent.Figures) -> "FiguresView":
        return cls(
            misses=figures.misses,
            misses_outstanding=figures.misses_outstanding,
            recoveries=[list(pair) for pair in figures.recoveries],
            chore_pay_awarded=figures.chore_pay_awarded,
            chore_pay_at_stake_pence=figures.chore_pay_at_stake_pence,
            chore_pay_pence=figures.chore_pay_pence,
            bonus_pence=figures.bonus_pence,
            reward_pence=figures.reward_pence,
            total_pence=figures.total_pence,
        )


class ConsequenceView(BaseModel):
    """What the batch does to one week, said in the week's own terms."""

    week_id: int
    start_date: str
    end_date: str
    confirmed: int
    rejected: int
    before: FiguresView
    after: FiguresView
    difference_pence: int
    rescues_the_chore_pay: bool
    loses_the_chore_pay: bool

    @classmethod
    def of(cls, consequence: parent.Consequence) -> "ConsequenceView":
        return cls(
            week_id=consequence.week_id,
            start_date=consequence.start_date.isoformat(),
            end_date=consequence.end_date.isoformat(),
            confirmed=consequence.confirmed,
            rejected=consequence.rejected,
            before=FiguresView.of(consequence.before),
            after=FiguresView.of(consequence.after),
            difference_pence=consequence.difference_pence,
            rescues_the_chore_pay=consequence.rescues_the_chore_pay,
            loses_the_chore_pay=consequence.loses_the_chore_pay,
        )


# --- What comes in ---------------------------------------------------------


class DecisionIn(BaseModel):
    instance_id: int
    decision: str

    @field_validator("decision")
    @classmethod
    def one_of_two(cls, decision: str) -> str:
        if decision not in ("confirm", "reject"):
            raise ValueError("A decision is either 'confirm' or 'reject'.")
        return decision


class PreviewRequest(BaseModel):
    """A batch, asked about rather than applied. No PIN: nothing happens."""

    decisions: list[DecisionIn] = Field(min_length=1)

    def decided(self) -> list[Decision]:
        return [
            Decision(instance_id=item.instance_id, decision=item.decision)  # type: ignore[arg-type]
            for item in self.decisions
        ]


# --- Endpoints -------------------------------------------------------------


@router.get("/queue", response_model=list[PendingView])
def queue(session: Session = Depends(get_session)) -> list[PendingView]:
    """Every claim waiting to be ruled on, oldest first, across open weeks."""
    return [
        PendingView(
            instance_id=claim.instance_id,
            definition_id=claim.definition_id,
            name=claim.name,
            category=claim.category,
            cadence=claim.cadence,
            amount_pence=claim.amount_pence,
            sequence=claim.sequence,
            due_date=claim.due_date.isoformat() if claim.due_date else None,
            week_id=claim.week_id,
            week_start_date=claim.week_start_date.isoformat(),
            claimed_at=claim.claimed_at,
            rejection_count=claim.rejection_count,
        )
        for claim in parent.pending(session)
    ]


@router.post("/review/preview", response_model=list[ConsequenceView])
def preview_review(
    body: PreviewRequest, session: Session = Depends(get_session)
) -> list[ConsequenceView]:
    """What this batch would do to each week it touches. Applies nothing.

    Refused for the same reasons the commit would refuse it, and by the same
    code — which is the point of knowing before a PIN is typed rather than
    after.
    """
    try:
        consequences = parent.preview(
            session,
            body.decided(),
            get_settings().tzinfo,
            at=utcnow(),
        )
    except ReviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    except NotOpen as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from None
    finally:
        # The preview rolled its savepoint back; this makes sure the request
        # cannot commit anything on its way out either.
        session.rollback()

    return [ConsequenceView.of(consequence) for consequence in consequences]
