"""Rewards a parent enters directly.

Not a chore, and deliberately not assessed like one. A reward is recorded
because something happened — an award at school, a kindness, a job nobody
asked for — and it is independent of how the week's chores went. A terrible
week at the hoover does not make the award smaller, and a voided week does not
take it back.

So a reward goes straight to the earnings ledger with its reason, belongs to
the week it was entered in, and never touches that week's settled figures.

It always belongs to an *open* week. If the week it was entered in has already
closed, it is carried to the next open one — see open_week_for below for why
that, and not the alternatives.

Amounts may be given as pence or as something a person would type. That is the
only place pounds exist in this service, and app.services.money is the only
thing that knows about them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import EarningType, WeekStatus
from app.models.ledgers import EarningEntry
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services.calendar import DAYS_IN_WEEK, today, week_containing
from app.services.money import MoneyError, format_pence, parse_pence

router = APIRouter(prefix="/api/rewards", tags=["rewards"])


@dataclass(frozen=True)
class RewardPreset:
    """A reward with a fixed name and a fixed amount.

    Both are fixed on purpose. The name is what he calls it, so it is what
    makes the ledger readable a year later — not "reward, £3" but "Eagle
    award". And the amount is what the scheme says it is worth, not a
    starting point for a conversation on the night.
    """

    key: str
    name: str
    amount_pence: int


#: Presets, as data. Adding one is a line here and nothing else.
REWARD_PRESETS: dict[str, RewardPreset] = {
    # £3 every time the school gives him one, however many that is.
    "eagle_award": RewardPreset(
        key="eagle_award",
        name="Eagle award",
        amount_pence=300,
    ),
}


# --- What comes in ---------------------------------------------------------


class RewardRequest(AuthorisedRequest):
    """An amount, and why. Both required — an amount with no reason is
    unexplainable three months later, which is when it will be asked about."""

    reason: str = Field(min_length=1)
    amount_pence: int | None = Field(default=None, ge=0)
    amount: str | None = None
    occurred_on: date | None = None

    @model_validator(mode="after")
    def exactly_one_amount(self) -> RewardRequest:
        if (self.amount_pence is None) == (self.amount is None):
            raise ValueError("Give the amount once: either amount_pence or amount.")
        return self

    def pence(self) -> int:
        if self.amount_pence is not None:
            return self.amount_pence
        return parse_pence(self.amount)


class PresetRequest(AuthorisedRequest):
    """A preset. The amount is the preset's, and is not open to negotiation.

    An amount sent with this is refused rather than ignored: silently
    substituting a different number for the one that was asked for is worse
    than saying no. Use /api/rewards for a reward of your own choosing.
    """

    occurred_on: date | None = None

    # Declared only so that sending one can be refused by name.
    amount_pence: int | None = None
    amount: str | None = None

    @model_validator(mode="after")
    def the_amount_is_the_presets(self) -> PresetRequest:
        if self.amount_pence is not None or self.amount is not None:
            raise ValueError(
                "This preset has a fixed amount. Use /api/rewards to record a"
                " reward of a different amount."
            )
        return self


# --- What goes out ---------------------------------------------------------


class RewardView(BaseModel):
    id: int
    amount_pence: int
    amount: str
    reason: str
    week_id: int
    week_start_date: str
    occurred_on: str
    #: True when the reward's own week had already closed and it was carried
    #: to an open one. Reported so nobody has to work out where it went.
    carried_to_an_open_week: bool


class PresetView(BaseModel):
    key: str
    name: str
    amount_pence: int
    amount: str


# --- Helpers ---------------------------------------------------------------


def open_week_for(session: Session, day: date) -> Week:
    """The open week a reward belongs to. Never a closed one, never none.

    Ordinarily this is the week the reward was entered in, created if nothing
    has happened in it yet — a reward entered on a Tuesday belongs to that
    week rather than to nothing.

    If that week has already settled, the reward moves to the next open week
    instead, and if there is no open week at all, one is opened after the
    latest week on record. He gets it with the next lot of money.

    It moves rather than staying put because a closed week is closed forever
    and cannot take it, and it moves rather than being recorded against no
    week because the earnings ledger is append-only: there is no paid_at to
    write on a ledger row, so a reward attached to nothing could never be
    marked as handed over. Every reward has to land somewhere that can be
    paid, and a week is the only thing that can be.
    """
    period = week_containing(day, get_settings().tzinfo)
    week = session.query(Week).filter(Week.start_date == period.start).one_or_none()

    if week is None:
        week = Week(start_date=period.start, end_date=period.end)
        session.add(week)
        session.flush()
        return week

    if week.status is WeekStatus.OPEN:
        return week

    later = (
        session.query(Week)
        .filter(Week.start_date > period.start, Week.status == WeekStatus.OPEN)
        .order_by(Week.start_date)
        .first()
    )
    if later is not None:
        return later

    latest = session.query(Week).order_by(Week.start_date.desc()).first()
    following = week_containing(
        latest.start_date + timedelta(days=DAYS_IN_WEEK), get_settings().tzinfo
    )
    week = Week(start_date=following.start, end_date=following.end)
    session.add(week)
    session.flush()
    return week


def _record(session: Session, *, pence: int, reason: str, day: date) -> EarningEntry:
    week = open_week_for(session, day)
    entry = EarningEntry(
        entry_type=EarningType.REWARD,
        amount_pence=pence,
        week_id=week.id,
        occurred_on=day,
        reason=reason.strip(),
    )
    session.add(entry)
    session.flush()
    return entry


def _view(entry: EarningEntry, week: Week) -> RewardView:
    return RewardView(
        id=entry.id,
        amount_pence=entry.amount_pence,
        amount=format_pence(entry.amount_pence),
        reason=entry.reason,
        week_id=entry.week_id,
        week_start_date=week.start_date.isoformat(),
        occurred_on=entry.occurred_on.isoformat(),
        carried_to_an_open_week=not (
            week.start_date <= entry.occurred_on <= week.end_date
        ),
    )


# --- Endpoints -------------------------------------------------------------


@router.get("/presets", response_model=list[PresetView])
def list_presets() -> list[PresetView]:
    """The presets on offer. Reading them gives nothing away, so no PIN."""
    return [
        PresetView(
            key=preset.key,
            name=preset.name,
            amount_pence=preset.amount_pence,
            amount=format_pence(preset.amount_pence),
        )
        for preset in REWARD_PRESETS.values()
    ]


@router.post("", response_model=RewardView, status_code=status.HTTP_201_CREATED)
def record_reward(
    request: Request,
    body: RewardRequest,
    session: Session = Depends(get_session),
) -> RewardView:
    """Record a reward. Money, so it carries the PIN."""
    authorise(request, body)
    day = body.occurred_on or today(get_settings().tzinfo)

    try:
        entry = _record(session, pence=body.pence(), reason=body.reason, day=day)
        session.commit()
    except MoneyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    return _view(entry, session.get(Week, entry.week_id))


@router.post(
    "/presets/{key}", response_model=RewardView, status_code=status.HTTP_201_CREATED
)
def record_preset(
    key: str,
    request: Request,
    body: PresetRequest,
    session: Session = Depends(get_session),
) -> RewardView:
    """Record a reward from a preset, at the preset's amount.

    There is no limit on how many times: the school decides how often it hands
    one out, and the scheme pays for each of them.
    """
    authorise(request, body)

    preset = REWARD_PRESETS.get(key)
    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No reward preset called {key!r}.",
        )

    day = body.occurred_on or today(get_settings().tzinfo)
    try:
        entry = _record(session, pence=preset.amount_pence, reason=preset.name, day=day)
        session.commit()
    except MoneyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    return _view(entry, session.get(Week, entry.week_id))
