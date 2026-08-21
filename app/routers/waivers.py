"""Waiving a day, or one chore for one week.

A waiver is not forgiveness. It means no assessable occasion existed in the
first place, which produces different figures from a miss that was excused:
the weekly counts scale down by the days away rather than being failed.

Recording one therefore has to change the week's instances, not just add a
row. `sync_week_instances` does that, and it removes an occasion the plan no
longer wants **only while it is still untouched** — waiving Monday after the
child's claim was confirmed leaves the claim standing for a parent to decide
about. Silently deleting somebody's confirmed work is not a thing this app
does, and a waiver is not a way in through the back.

Waiving carries the PIN because it moves money: a day away can rescue a week
that would otherwise fail, and "we were out on Monday" is exactly the kind of
claim that has to come from a parent rather than from whoever loaded the page.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chores import ChoreDefinition
from app.models.enums import WaiverScope, WeekStatus
from app.models.waivers import Waiver
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services.calendar import week_containing
from app.services.instances import plan_week, sync_week_instances
from app.services.settlement import week_period

router = APIRouter(prefix="/api/waivers", tags=["waivers"])


# --- What comes in and out -------------------------------------------------


class WaiverRequest(AuthorisedRequest):
    """Either a day, or a chore for a week. Never both, never neither."""

    scope: str
    day: date | None = None
    week_id: int | None = None
    definition_id: int | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def each_scope_carries_its_own(self) -> "WaiverRequest":
        if self.scope == WaiverScope.DAY.value:
            if self.day is None:
                raise ValueError("Waiving a day needs the day.")
            if self.definition_id is not None:
                raise ValueError(
                    "A day is waived for everything. Waive a chore for a week"
                    " if you meant one chore."
                )
        elif self.scope == WaiverScope.CHORE_WEEK.value:
            if self.week_id is None or self.definition_id is None:
                raise ValueError("Waiving a chore for a week needs both.")
            if self.day is not None:
                raise ValueError("A chore-week waiver covers the week, not a day.")
        else:
            raise ValueError("A waiver is scoped to 'day' or to 'chore_week'.")
        return self


class WaiverView(BaseModel):
    id: int
    scope: str
    day: str | None
    week_id: int | None
    definition_id: int | None
    definition_name: str | None
    reason: str | None
    instances_removed: int = 0


def _view(session: Session, waiver: Waiver, removed: int = 0) -> WaiverView:
    name = None
    if waiver.definition_id is not None:
        definition = session.get(ChoreDefinition, waiver.definition_id)
        name = definition.name if definition else None
    return WaiverView(
        id=waiver.id,
        scope=waiver.scope.value,
        day=waiver.day.isoformat() if waiver.day else None,
        week_id=waiver.week_id,
        definition_id=waiver.definition_id,
        definition_name=name,
        reason=waiver.reason,
        instances_removed=removed,
    )


# --- Endpoints -------------------------------------------------------------


@router.get("", response_model=list[WaiverView])
def list_waivers(session: Session = Depends(get_session)) -> list[WaiverView]:
    """Every waiver on record. Reading needs no PIN."""
    waivers = session.query(Waiver).order_by(Waiver.id).all()
    return [_view(session, waiver) for waiver in waivers]


@router.post("", response_model=WaiverView, status_code=status.HTTP_201_CREATED)
def record_waiver(
    request: Request,
    body: WaiverRequest,
    session: Session = Depends(get_session),
) -> WaiverView:
    """Waive a day, or a chore for a week, and re-plan the week it lands in."""
    authorise(request, body)
    settings = get_settings()

    week = _week_for(session, body)
    if week is not None and week.status is not WeekStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Week {week.start_date.isoformat()} is {week.status.value}."
                " A closed week is not re-planned; its figures are stored."
            ),
        )

    if body.definition_id is not None and session.get(ChoreDefinition, body.definition_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chore {body.definition_id}.",
        )

    waiver = Waiver(
        scope=WaiverScope(body.scope),
        day=body.day,
        week_id=body.week_id,
        definition_id=body.definition_id,
        reason=body.reason,
    )
    session.add(waiver)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That waiver is already recorded.",
        ) from None

    removed = 0
    if week is not None:
        plan = plan_week(
            week_period(week, settings.tzinfo),
            session.query(ChoreDefinition).all(),
            session.query(Waiver).all(),
            week_id=week.id,
        )
        _, removed = sync_week_instances(session, week, plan)

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(waiver)
    return _view(session, waiver, removed)


def _week_for(session: Session, body: WaiverRequest) -> Week | None:
    """The week this waiver re-plans, if the week exists yet.

    A day waiver for a week nothing has happened in has no week row to
    re-plan, and that is fine: the waiver is on record and the plan will read
    it the first time the week is opened.
    """
    if body.week_id is not None:
        week = session.get(Week, body.week_id)
        if week is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No week {body.week_id}.",
            )
        return week

    period = week_containing(body.day, get_settings().tzinfo)
    return session.query(Week).filter(Week.start_date == period.start).one_or_none()
