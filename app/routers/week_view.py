"""The child's week: what it asks for, what he has done, what it will pay.

Reading needs no credential. The whole point of this screen is that the child
can see where he stands without asking, and nothing on it changes anything.
The one button it carries — claiming — is the existing unauthenticated claim
endpoint, because a claim is a request to be believed rather than money.

`POST /api/week/open` is the exception, and it is a write on purpose. A week
exists as a row only once something has happened in it, and its instances only
exist once somebody has generated them from the plan, so the first load of a
Sunday morning would otherwise show an empty screen and no way to fix it. It
is idempotent, it decides no money, and `sync_week_instances` never touches an
instance that already exists — so calling it every time the screen loads is
safe and is what the frontend does.

It carries no PIN for the same reason claiming does not: it asserts nothing
about what was done. The worst a stranger with the URL can do is bring into
being the week that was going to exist anyway.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chores import ChoreDefinition
from app.models.enums import WeekStatus
from app.models.waivers import Waiver
from app.models.weeks import Week
from app.routers.dependencies import get_session
from app.services import week_view
from app.services.calendar import current_week
from app.services.instances import plan_week, sync_week_instances
from app.services.settlement import week_period

router = APIRouter(prefix="/api/week", tags=["week"])


# --- What goes out ---------------------------------------------------------


class InstanceCardView(BaseModel):
    instance_id: int | None
    definition_id: int
    name: str
    category: str
    cadence: str
    amount_pence: int
    state: str
    sequence: int
    due_date: str | None
    can_claim: bool
    rejection_count: int
    miss_origin: str | None

    @classmethod
    def of(cls, card: week_view.InstanceCard) -> "InstanceCardView":
        return cls(
            instance_id=card.instance_id,
            definition_id=card.definition_id,
            name=card.name,
            category=card.category.value,
            cadence=card.cadence.value,
            amount_pence=card.amount_pence,
            state=card.state,
            sequence=card.sequence,
            due_date=card.due_date.isoformat() if card.due_date else None,
            can_claim=card.can_claim,
            rejection_count=card.rejection_count,
            miss_origin=card.miss_origin,
        )


class DayCardView(BaseModel):
    day: str
    weekday: str
    is_today: bool
    is_past: bool
    waived: bool
    waiver_reason: str | None
    chores: list[InstanceCardView]


class WeeklyCardView(BaseModel):
    definition_id: int
    name: str
    category: str
    cadence: str
    amount_pence: int
    required: int
    confirmed: int
    claimed: int
    instances: list[InstanceCardView]
    judged_at_settlement: bool
    waived: bool


class RecoveryNeedView(BaseModel):
    definition_id: int
    miss_name: str
    covered_by: str | None


class RecoveryPanelView(BaseModel):
    needs: list[RecoveryNeedView]
    outstanding: int
    covered: int
    cap: int
    deadline: str
    seconds_remaining: int
    days_remaining: int
    urgent: bool
    options: list[InstanceCardView]
    spent: list[InstanceCardView]


class TotalsView(BaseModel):
    base_pence: int
    chore_pay_at_stake_pence: int
    chore_pay_pence: int
    chore_pay_awarded: bool
    bonus_pence: int
    reward_pence: int
    ad_hoc_reward_pence: int
    held_as_makegood_pence: int
    total_pence: int
    payable_total_pence: int


class WeekViewOut(BaseModel):
    child_name: str
    week_id: int
    start_date: str
    end_date: str
    status: str
    today: str
    is_current: bool
    days: list[DayCardView]
    weekly: list[WeeklyCardView]
    waived_days: list[str]
    recovery: RecoveryPanelView
    totals: TotalsView

    @classmethod
    def of(cls, view: week_view.WeekView) -> "WeekViewOut":
        return cls(
            child_name=view.child_name,
            week_id=view.week_id,
            start_date=view.start_date.isoformat(),
            end_date=view.end_date.isoformat(),
            status=view.status.value,
            today=view.today.isoformat(),
            is_current=view.is_current,
            days=[
                DayCardView(
                    day=day.day.isoformat(),
                    weekday=day.weekday,
                    is_today=day.is_today,
                    is_past=day.is_past,
                    waived=day.waived,
                    waiver_reason=day.waiver_reason,
                    chores=[InstanceCardView.of(card) for card in day.chores],
                )
                for day in view.days
            ],
            weekly=[
                WeeklyCardView(
                    definition_id=card.definition_id,
                    name=card.name,
                    category=card.category.value,
                    cadence=card.cadence.value,
                    amount_pence=card.amount_pence,
                    required=card.required,
                    confirmed=card.confirmed,
                    claimed=card.claimed,
                    instances=[
                        InstanceCardView.of(instance) for instance in card.instances
                    ],
                    judged_at_settlement=card.judged_at_settlement,
                    waived=card.waived,
                )
                for card in view.weekly
            ],
            waived_days=[day.isoformat() for day in view.waived_days],
            recovery=RecoveryPanelView(
                needs=[
                    RecoveryNeedView(
                        definition_id=need.definition_id,
                        miss_name=need.miss_name,
                        covered_by=need.covered_by,
                    )
                    for need in view.recovery.needs
                ],
                outstanding=view.recovery.outstanding,
                covered=view.recovery.covered,
                cap=view.recovery.cap,
                deadline=view.recovery.deadline.isoformat(),
                seconds_remaining=view.recovery.seconds_remaining,
                days_remaining=view.recovery.days_remaining,
                urgent=view.recovery.urgent,
                options=[InstanceCardView.of(card) for card in view.recovery.options],
                spent=[InstanceCardView.of(card) for card in view.recovery.spent],
            ),
            totals=TotalsView(
                base_pence=view.totals.base_pence,
                chore_pay_at_stake_pence=view.totals.chore_pay_at_stake_pence,
                chore_pay_pence=view.totals.chore_pay_pence,
                chore_pay_awarded=view.totals.chore_pay_awarded,
                bonus_pence=view.totals.bonus_pence,
                reward_pence=view.totals.reward_pence,
                ad_hoc_reward_pence=view.totals.ad_hoc_reward_pence,
                held_as_makegood_pence=view.totals.held_as_makegood_pence,
                total_pence=view.totals.total_pence,
                payable_total_pence=view.totals.payable_total_pence,
            ),
        )


# --- Helpers ---------------------------------------------------------------


def _week_starting(session: Session, start: date) -> Week | None:
    return session.query(Week).filter(Week.start_date == start).one_or_none()


def _view(session: Session, week: Week) -> WeekViewOut:
    """Build the view. Works for a closed week too — see week_view.build —
    reading its stored figures rather than a proposal, so paging back to a
    settled week is just this, not a second endpoint."""
    return WeekViewOut.of(week_view.build(session, week, get_settings().tzinfo))


# --- Endpoints -------------------------------------------------------------


@router.post("/open", response_model=WeekViewOut)
def open_current_week(session: Session = Depends(get_session)) -> WeekViewOut:
    """Make sure this week exists and asks for what the scheme says it asks.

    Idempotent, and safe to call on every load: an instance that already
    exists is left exactly as it is, claims and confirmations included.
    """
    settings = get_settings()
    period = current_week(settings.tzinfo)

    week = _week_starting(session, period.start)
    if week is None:
        week = Week(start_date=period.start, end_date=period.end)
        session.add(week)
        session.flush()

    if week.status is WeekStatus.OPEN:
        plan = plan_week(
            week_period(week, settings.tzinfo),
            session.query(ChoreDefinition).all(),
            session.query(Waiver).all(),
            week_id=week.id,
        )
        sync_week_instances(session, week, plan)

    session.commit()
    session.refresh(week)
    return _view(session, week)


@router.get("", response_model=WeekViewOut)
def get_current_week(session: Session = Depends(get_session)) -> WeekViewOut:
    """This week, as the child reads it."""
    period = current_week(get_settings().tzinfo)
    week = _week_starting(session, period.start)
    if week is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "This week has not been opened yet."
                " POST /api/week/open brings it into being."
            ),
        )
    return _view(session, week)


@router.get("/{week_id}", response_model=WeekViewOut)
def get_week(week_id: int, session: Session = Depends(get_session)) -> WeekViewOut:
    """Any week, open or closed, in the same shape.

    A closed week comes back read-only: its own stored figures, no recovery
    route, nothing claimable. This is what lets a screen page back through
    history without a second endpoint to know about.
    """
    week = session.get(Week, week_id)
    if week is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No week {week_id}."
        )
    return _view(session, week)
