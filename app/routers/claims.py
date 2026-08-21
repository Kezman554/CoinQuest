"""Claiming chores, and a parent ruling on what was claimed.

Two audiences, two rules.

The child claims, and that needs no credential. A claim is not money: it is a
request to be believed, and it stays pending until somebody says otherwise.
The worst a stranger with the URL can do is queue work for a parent to reject.

Everything that could turn into money — confirming, rejecting, marking a chore
missed — carries the PIN and is refused server-side without it. This module
assumes nothing about what the frontend chose to display. A request typed
straight at the API by somebody who never loaded the page meets the same
check.

A review is one transaction. Either every decision in it applies or none do,
so a parent working through a Sunday list never ends up half-committed to a
batch they will now have to reconstruct from memory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.chores import ChoreInstance
from app.models.enums import InstanceState, MissOrigin, WeekStatus
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services.review import (
    Decision as ServiceDecision,
    ReviewError,
    apply_decisions,
)

router = APIRouter(prefix="/api", tags=["claims"])


# --- What comes in ---------------------------------------------------------


class ClaimRequest(BaseModel):
    """The child saying a chore is done. No credential, by design."""

    instance_id: int


class Decision(BaseModel):
    """One ruling on one claim."""

    instance_id: int
    decision: Literal["confirm", "reject"]


class ReviewRequest(AuthorisedRequest):
    """A parent's batch of rulings, authorised once for the whole submission."""

    decisions: list[Decision] = Field(min_length=1)

    @field_validator("decisions")
    @classmethod
    def each_instance_appears_once(cls, decisions: list[Decision]) -> list[Decision]:
        seen = [decision.instance_id for decision in decisions]
        duplicates = {item for item in seen if seen.count(item) > 1}
        if duplicates:
            raise ValueError(
                f"Instances appear more than once in this batch: {sorted(duplicates)}"
            )
        return decisions

    def decided(self) -> list[ServiceDecision]:
        return [
            ServiceDecision(
                instance_id=decision.instance_id, decision=decision.decision
            )
            for decision in self.decisions
        ]


class MissedRequest(AuthorisedRequest):
    """A parent marking a chore missed without waiting for settlement."""

    instance_id: int
    note: str | None = None


# --- What goes out. Never the PIN, which is not in these models at all. -----


class InstanceView(BaseModel):
    id: int
    definition_id: int
    week_id: int
    due_date: str | None
    sequence: int
    state: str
    claimed_at: datetime | None
    confirmed_at: datetime | None
    missed_at: datetime | None
    miss_origin: str | None
    rejected_at: datetime | None
    rejection_count: int
    authorised_by: str | None

    @classmethod
    def of(cls, instance: ChoreInstance) -> InstanceView:
        return cls(
            id=instance.id,
            definition_id=instance.definition_id,
            week_id=instance.week_id,
            due_date=instance.due_date.isoformat() if instance.due_date else None,
            sequence=instance.sequence,
            state=instance.state.value,
            claimed_at=instance.claimed_at,
            confirmed_at=instance.confirmed_at,
            missed_at=instance.missed_at,
            miss_origin=instance.miss_origin.value if instance.miss_origin else None,
            rejected_at=instance.rejected_at,
            rejection_count=instance.rejection_count,
            authorised_by=instance.authorised_by,
        )


class ReviewResult(BaseModel):
    confirmed: list[int]
    rejected: list[int]
    authorised_by: str


# --- Shared checks ---------------------------------------------------------


def _load(session: Session, instance_id: int) -> ChoreInstance:
    instance = session.get(ChoreInstance, instance_id)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chore instance {instance_id}.",
        )
    return instance


def _refuse_closed_weeks(session: Session, instance: ChoreInstance) -> None:
    """A settled or voided week is closed forever, including to a claim."""
    week = session.get(Week, instance.week_id)
    if week is not None and week.status is not WeekStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Week {week.start_date.isoformat()} is {week.status.value};"
                " it cannot be changed."
            ),
        )


# --- The child's endpoint --------------------------------------------------


@router.post("/claims", response_model=InstanceView, status_code=status.HTTP_200_OK)
def claim(body: ClaimRequest, session: Session = Depends(get_session)) -> InstanceView:
    """Claim an instance. Unauthenticated, and pending until a parent rules.

    Claiming is not an assertion that money is owed; it is a request to be
    believed. Nothing here can pay anything.
    """
    instance = _load(session, body.instance_id)
    _refuse_closed_weeks(session, instance)

    if instance.state is InstanceState.CLAIMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That chore is already claimed and waiting to be confirmed.",
        )
    if instance.state is not InstanceState.UNTOUCHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That chore is already {instance.state.value}.",
        )

    instance.state = InstanceState.CLAIMED
    instance.claimed_at = utcnow()
    # rejected_at and rejection_count are deliberately left alone. Claiming
    # again does not unhappen a rejection.
    session.commit()
    session.refresh(instance)
    return InstanceView.of(instance)


# --- The parent's endpoints ------------------------------------------------


@router.post("/claims/review", response_model=ReviewResult)
def review(
    request: Request,
    body: ReviewRequest,
    session: Session = Depends(get_session),
) -> ReviewResult:
    """Rule on a batch of claims. One PIN, one transaction, all or nothing.

    The PIN is checked before anything is read, and every decision is applied
    to the session before anything is committed. If one of them cannot be
    applied, the whole submission is rolled back and the parent is told which
    item stopped it — so they can fix that one and resubmit the same batch
    rather than work out which half went through.

    The applying itself lives in app.services.review, because the parent view
    asks what a batch *would* do before this is called and the two answers
    have to come from the same code. A preview that agrees with the commit
    only by coincidence is not a preview.
    """
    authorisation = authorise(request, body)

    try:
        applied = apply_decisions(session, body.decided(), authorisation)
        session.commit()
    except ReviewError as exc:
        # Including this one: a refusal must leave the database exactly as it
        # found it.
        session.rollback()
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if str(exc).startswith("No chore instance")
                else status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from None
    except Exception:
        session.rollback()
        raise

    return ReviewResult(
        confirmed=list(applied.confirmed),
        rejected=list(applied.rejected),
        authorised_by=authorisation.party,
    )


@router.post("/instances/{instance_id}/missed", response_model=InstanceView)
def mark_missed(
    instance_id: int,
    request: Request,
    body: MissedRequest,
    session: Session = Depends(get_session),
) -> InstanceView:
    """Mark a chore missed now, rather than letting settlement decide.

    This is what makes the recovery window usable: told on Tuesday that
    Monday was missed, the child has the rest of the week to work it back.
    """
    authorisation = authorise(request, body)

    if body.instance_id != instance_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The instance in the path and in the body must agree.",
        )

    try:
        instance = _load(session, instance_id)
        _refuse_closed_weeks(session, instance)

        if instance.state is InstanceState.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "That chore is already confirmed. Confirmed work is not"
                    " taken back by marking it missed."
                ),
            )

        instance.state = InstanceState.MISSED
        instance.missed_at = authorisation.at
        # A parent deciding this is definite, and names them. A miss the
        # settlement infers later does neither.
        instance.miss_origin = MissOrigin.PARENT_MARKED
        instance.authorised_by = authorisation.party
        instance.claimed_at = None
        if body.note:
            instance.notes = body.note
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(instance)
    return InstanceView.of(instance)
