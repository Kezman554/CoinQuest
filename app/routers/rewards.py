"""Rewards a parent enters directly.

Not a chore, and deliberately not assessed like one. A reward is recorded
because something happened — an award at school, a kindness, a job nobody
asked for — and it is independent of how the week's chores went. A terrible
week at the hoover does not make the award smaller, and a voided week does not
take it back.

So a reward goes straight to the earnings ledger with its reason, belongs to
the week it was entered in, and never touches that week's settled figures.

Amounts may be given as pence or as something a person would type. That is the
only place pounds exist in this service, and app.services.money is the only
thing that knows about them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import EarningType
from app.models.ledgers import EarningEntry
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services.calendar import today, week_containing
from app.services.money import MoneyError, format_pence, parse_pence

router = APIRouter(prefix="/api/rewards", tags=["rewards"])


@dataclass(frozen=True)
class RewardPreset:
    """A reward given often enough to be worth not retyping.

    The amount is a default rather than a fixed price: the preset exists to
    save typing the name and the reason, not to decide what something is worth
    this time.
    """

    key: str
    name: str
    default_amount_pence: int
    reason: str


#: Presets, as data. Adding one is a line here and nothing else.
REWARD_PRESETS: dict[str, RewardPreset] = {
    "school_award": RewardPreset(
        key="school_award",
        name="School award",
        default_amount_pence=100,
        reason="School award",
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
    """A preset, optionally at a different amount from its usual one."""

    amount_pence: int | None = Field(default=None, ge=0)
    amount: str | None = None
    occurred_on: date | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def at_most_one_amount(self) -> PresetRequest:
        if self.amount_pence is not None and self.amount is not None:
            raise ValueError("Give the amount once: either amount_pence or amount.")
        return self

    def pence(self, preset: RewardPreset) -> int:
        if self.amount_pence is not None:
            return self.amount_pence
        if self.amount is not None:
            return parse_pence(self.amount)
        return preset.default_amount_pence


# --- What goes out ---------------------------------------------------------


class RewardView(BaseModel):
    id: int
    amount_pence: int
    amount: str
    reason: str
    week_id: int
    occurred_on: str


class PresetView(BaseModel):
    key: str
    name: str
    default_amount_pence: int
    default_amount: str


# --- Helpers ---------------------------------------------------------------


def week_for(session: Session, day: date) -> Week:
    """The week a reward entered today belongs to.

    Created if it does not exist yet. A reward can be entered on a Tuesday
    before anything else has happened that week, and it still belongs to that
    week rather than to nothing.
    """
    period = week_containing(day, get_settings().tzinfo)
    week = session.query(Week).filter(Week.start_date == period.start).one_or_none()
    if week is None:
        week = Week(start_date=period.start, end_date=period.end)
        session.add(week)
        session.flush()
    return week


def _record(session: Session, *, pence: int, reason: str, day: date) -> EarningEntry:
    week = week_for(session, day)
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


def _view(entry: EarningEntry) -> RewardView:
    return RewardView(
        id=entry.id,
        amount_pence=entry.amount_pence,
        amount=format_pence(entry.amount_pence),
        reason=entry.reason,
        week_id=entry.week_id,
        occurred_on=entry.occurred_on.isoformat(),
    )


# --- Endpoints -------------------------------------------------------------


@router.get("/presets", response_model=list[PresetView])
def list_presets() -> list[PresetView]:
    """The presets on offer. Reading them gives nothing away, so no PIN."""
    return [
        PresetView(
            key=preset.key,
            name=preset.name,
            default_amount_pence=preset.default_amount_pence,
            default_amount=format_pence(preset.default_amount_pence),
        )
        for preset in REWARD_PRESETS.values()
    ]


@router.post("", response_model=RewardView, status_code=status.HTTP_201_CREATED)
def record_reward(
    body: RewardRequest, session: Session = Depends(get_session)
) -> RewardView:
    """Record a reward. Money, so it carries the PIN."""
    authorise(body)
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

    return _view(entry)


@router.post(
    "/presets/{key}", response_model=RewardView, status_code=status.HTTP_201_CREATED
)
def record_preset(
    key: str, body: PresetRequest, session: Session = Depends(get_session)
) -> RewardView:
    """Record a reward from a preset, at its usual amount unless told otherwise."""
    authorise(body)

    preset = REWARD_PRESETS.get(key)
    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No reward preset called {key!r}.",
        )

    day = body.occurred_on or today(get_settings().tzinfo)
    try:
        entry = _record(
            session,
            pence=body.pence(preset),
            reason=body.reason or preset.reason,
            day=day,
        )
        session.commit()
    except MoneyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    except Exception:
        session.rollback()
        raise

    return _view(entry)
