"""Claiming chores, and a parent ruling on what was claimed.

Two audiences, two rules.

The child claims, and that needs no credential. A claim is not money: it is a
request to be believed, and it stays pending until somebody says otherwise.
The worst a stranger with the URL can do is queue work for a parent to reject.

The rule this module used to state was: "everything that could turn into
money — confirming, rejecting, marking a chore missed — carries the PIN".
That sentence is written out here rather than deleted, because the half of it
that changed would otherwise read as an oversight.

The rule now is: **the PIN guards what hands money over or gives it back, not
what proposes losing it.** Confirming and rejecting still carry it. Marking a
chore missed no longer does, and clearing a mark does.

Marking a miss is a proposal in exactly the sense a claim is. It pays nothing,
and nothing is paid until settlement — which is PIN-guarded, states the figure
before it asks, and, since Session V, can be reopened if it was agreed
wrongly. What the requirement actually is: a parent notices at the sink that
yesterday was missed, and has about ten seconds to record it before the moment
passes. Four digits on a wall screen defeats that, and a miss not recorded on
the day is a recovery window the child never gets told about, which is the
whole thing the window exists for.

Clearing a miss is the other half, and it is guarded. The asymmetry is
deliberate and is the shape of the whole screen: anything that costs him money
is a tap, anything that gives it back is a parent. The worst an unauthorised
tap can now do is understate a week, in public, on a screen the household
reads a dozen times a day, with a parent-only undo sitting beside it.

This module assumes nothing about what the frontend chose to display. A
request typed straight at the API by somebody who never loaded the page meets
exactly these same checks.

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


class MissedRequest(BaseModel):
    """Marking a chore missed without waiting for settlement. No PIN.

    See the module docstring for why this one carries no credential and
    ClearMissRequest does.
    """

    instance_id: int
    note: str | None = None


class ClearMissRequest(AuthorisedRequest):
    """A parent taking a mark back. Authorised, because it gives money back."""

    instance_id: int


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
    body: MissedRequest,
    session: Session = Depends(get_session),
) -> InstanceView:
    """Mark a chore missed now, rather than letting settlement decide.

    This is what makes the recovery window usable: told on Tuesday that
    Monday was missed, the child has the rest of the week to work it back.
    Told at settlement, he is told about a window that has already shut.

    No PIN — see the module docstring, which states the rule this reverses
    and why. Undone by clear_miss, which does carry one.
    """
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
        instance.missed_at = utcnow()
        # Still PARENT_MARKED, and it still means what it always meant: a
        # miss somebody decided while the week was open, as against one
        # settlement inferred from silence after it closed. That is what
        # makes it definite, what makes it recoverable, and — see clear_miss
        # — what makes it the only kind that can be taken back.
        instance.miss_origin = MissOrigin.PARENT_MARKED
        # Nobody authorised this any more, so nobody is named. Cleared rather
        # than left, for record_inferred_misses' own reason: a parent who
        # rejected a claim on this instance earlier in the week is still
        # sitting in this column, and leaving them there would read as though
        # they had ruled it missed.
        instance.authorised_by = None
        instance.claimed_at = None
        if body.note:
            instance.notes = body.note
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(instance)
    return InstanceView.of(instance)


@router.post("/instances/{instance_id}/missed/clear", response_model=InstanceView)
def clear_miss(
    instance_id: int,
    request: Request,
    body: ClearMissRequest,
    session: Session = Depends(get_session),
) -> InstanceView:
    """Take a mark back: the instance returns to untouched, claimable again.

    Authorised, because this is the direction that gives money back. A miss
    marked in error takes the whole chore pot off the week until it is
    cleared, so the undo is worth as much as the settlement it would
    otherwise distort — and it is the only control on the child's screen that
    asks for the PIN.

    Only a PARENT_MARKED miss can be cleared. A miss inferred at settlement
    belongs to a week that is already closed, and a closed week is closed
    forever — so refusing it by origin says out loud what the closed-week
    check would otherwise only say by accident.
    """
    authorise(request, body)

    if body.instance_id != instance_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The instance in the path and in the body must agree.",
        )

    try:
        instance = _load(session, instance_id)
        _refuse_closed_weeks(session, instance)

        if instance.state is not InstanceState.MISSED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"That chore is {instance.state.value}, not missed;"
                    " there is no mark on it to clear."
                ),
            )
        if instance.miss_origin is not MissOrigin.PARENT_MARKED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "That miss was worked out at settlement rather than"
                    " marked by a parent, so it cannot be cleared here."
                ),
            )

        instance.state = InstanceState.UNTOUCHED
        instance.missed_at = None
        instance.miss_origin = None
        instance.authorised_by = None
        # rejected_at and rejection_count survive, exactly as they survive a
        # re-claim. Clearing a miss does not unhappen a rejection.
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(instance)
    return InstanceView.of(instance)
