"""Chore definitions: creating, listing, editing and retiring the rules.

A definition is the rule; an instance is a fact about one day or one week —
see app/models/chores.py. Nothing here ever touches an instance directly.
Editing a definition changes what happens **from now on**: the next time the
current week is opened or re-synced, `instances.plan_week` reads the live
definition, exactly as it always has (see Session C's tests: renaming,
repricing or recategorising a chore leaves a settled week's stored figures
untouched, because a closed week keeps its own frozen copy of everything it
paid for — app/models/weeks.py's SettlementLine).

So that a chore appears on the current week's view the moment it is created,
edited or retired — rather than only the next time somebody happens to open
the week — every write here re-syncs *today's* week if one is open. This
mirrors app/routers/waivers.py, which does the same after recording a waiver.
Any other open week picks up the change the next time it is touched; that is
existing, already-tested behaviour and nothing new is done for it here.

Retiring is not deleting. `is_available` going false is the only thing a
retirement changes, because settled weeks and past instances still point at
the definition (chore_instances.definition_id is ON DELETE RESTRICT) and the
record of what was done has to survive. There is no delete endpoint: a
definition that was never claimed against could in principle be removed, but
retiring is the one operation this scheme performs on a chore nobody wants
any more, and it is the only one offered here.

All four writes carry the PIN, the same pattern as waivers and rewards: a new
chore, a changed amount or a retirement all shape what the scheme pays from
here on, which is exactly the class of thing this app requires a parent to
authorise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chores import ChoreDefinition
from app.models.enums import Cadence, Category, WeekStatus
from app.models.waivers import Waiver
from app.models.weeks import Week
from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services.calendar import current_week
from app.services.instances import plan_week, sync_week_instances
from app.services.settlement import week_period

router = APIRouter(prefix="/api/chores", tags=["chores"])


# --- What comes in -----------------------------------------------------------


class ChoreWriteRequest(AuthorisedRequest):
    """The whole rule, as create and edit both take it.

    Edit takes the same shape as create rather than a partial one: a form
    submits the complete, current truth about a chore, and a partial-update
    shape would leave `times_per_week` ambiguous between "unset it" and
    "leave it alone" for every cadence that does not use it.
    """

    name: str = Field(min_length=1, max_length=120)
    category: str
    cadence: str
    #: Required for, and only for, weekly_count — mirrors the CHECK constraint
    #: in the migration exactly, so a bad request is a clean 422 here rather
    #: than a raw IntegrityError from SQLite.
    times_per_week: int | None = Field(default=None, gt=0)
    amount_pence: int = Field(ge=0)
    is_administered: bool = False

    @model_validator(mode="after")
    def category_is_known(self) -> "ChoreWriteRequest":
        try:
            Category(self.category)
        except ValueError:
            options = ", ".join(value.value for value in Category)
            raise ValueError(f"category must be one of: {options}.") from None
        return self

    @model_validator(mode="after")
    def cadence_is_known(self) -> "ChoreWriteRequest":
        try:
            Cadence(self.cadence)
        except ValueError:
            options = ", ".join(value.value for value in Cadence)
            raise ValueError(f"cadence must be one of: {options}.") from None
        return self

    @model_validator(mode="after")
    def cadence_carries_its_own_fields(self) -> "ChoreWriteRequest":
        if self.cadence == Cadence.WEEKLY_COUNT.value:
            if self.times_per_week is None:
                raise ValueError(
                    "A weekly-count chore needs times_per_week — how many"
                    " times a week it is due."
                )
        elif self.times_per_week is not None:
            raise ValueError(
                "times_per_week only applies to a weekly-count chore."
            )
        return self


class RetireRequest(AuthorisedRequest):
    """Nothing but the PIN — retiring states no new fact beyond "not any more"."""


# --- What goes out ------------------------------------------------------------


class ChoreDefinitionView(BaseModel):
    id: int
    name: str
    category: str
    cadence: str
    times_per_week: int | None
    amount_pence: int
    is_administered: bool
    is_available: bool


def _view(definition: ChoreDefinition) -> ChoreDefinitionView:
    return ChoreDefinitionView(
        id=definition.id,
        name=definition.name,
        category=definition.category.value,
        cadence=definition.cadence.value,
        times_per_week=definition.times_per_week,
        amount_pence=definition.amount_pence,
        is_administered=definition.is_administered,
        is_available=definition.is_available,
    )


# --- Re-syncing today's week --------------------------------------------------


def _resync_current_week(session: Session) -> None:
    """Bring today's week's instances into line with the live definitions.

    Only today's week: an edit here is a change to the rules, not an act
    aimed at any particular week, so there is nothing to re-sync for a week
    that is not open or has not been opened yet — the next thing that reads
    or opens it will see the live definitions anyway, exactly as it always
    has. Mirrors waivers.py's `_week_for` / re-sync, scoped to "today"
    instead of to whatever day or week the request named.
    """
    settings = get_settings()
    period = current_week(settings.tzinfo)
    week = session.query(Week).filter(Week.start_date == period.start).one_or_none()
    if week is None or week.status is not WeekStatus.OPEN:
        return

    plan = plan_week(
        week_period(week, settings.tzinfo),
        session.query(ChoreDefinition).all(),
        session.query(Waiver).all(),
        week_id=week.id,
    )
    sync_week_instances(session, week, plan)


# --- Endpoints -----------------------------------------------------------------


@router.get("", response_model=list[ChoreDefinitionView])
def list_chores(session: Session = Depends(get_session)) -> list[ChoreDefinitionView]:
    """Every chore definition, retired ones included. Reading needs no PIN."""
    definitions = session.query(ChoreDefinition).order_by(ChoreDefinition.name).all()
    return [_view(definition) for definition in definitions]


@router.post("", response_model=ChoreDefinitionView, status_code=status.HTTP_201_CREATED)
def create_chore(
    request: Request,
    body: ChoreWriteRequest,
    session: Session = Depends(get_session),
) -> ChoreDefinitionView:
    """Add a chore to the scheme. Available from the moment it is created."""
    authorise(request, body)

    definition = ChoreDefinition(
        name=body.name.strip(),
        category=Category(body.category),
        cadence=Cadence(body.cadence),
        times_per_week=body.times_per_week,
        amount_pence=body.amount_pence,
        is_administered=body.is_administered,
    )
    session.add(definition)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A chore called {body.name.strip()!r} already exists.",
        ) from None

    _resync_current_week(session)

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(definition)
    return _view(definition)


@router.post("/{definition_id}", response_model=ChoreDefinitionView)
def edit_chore(
    definition_id: int,
    request: Request,
    body: ChoreWriteRequest,
    session: Session = Depends(get_session),
) -> ChoreDefinitionView:
    """Change the rule. Never touches a settled week's stored figures.

    Availability is not one of the fields here — see the module docstring.
    Retiring and un-retiring are not this endpoint's job.
    """
    authorise(request, body)

    definition = session.get(ChoreDefinition, definition_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chore {definition_id}.",
        )

    definition.name = body.name.strip()
    definition.category = Category(body.category)
    definition.cadence = Cadence(body.cadence)
    definition.times_per_week = body.times_per_week
    definition.amount_pence = body.amount_pence
    definition.is_administered = body.is_administered

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A chore called {body.name.strip()!r} already exists.",
        ) from None

    _resync_current_week(session)

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(definition)
    return _view(definition)


@router.post("/{definition_id}/retire", response_model=ChoreDefinitionView)
def retire_chore(
    definition_id: int,
    request: Request,
    body: RetireRequest,
    session: Session = Depends(get_session),
) -> ChoreDefinitionView:
    """Withdraw a chore from the scheme. Switched off, never deleted.

    An untouched instance of this chore in today's week is removed by the
    re-sync below, exactly as a waiver removes one — see
    instances.sync_week_instances. A claimed or confirmed instance is left
    exactly as it is: retiring is not a way to take back work already agreed.
    """
    authorise(request, body)

    definition = session.get(ChoreDefinition, definition_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chore {definition_id}.",
        )

    if not definition.is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{definition.name!r} is already retired.",
        )

    definition.is_available = False
    session.flush()

    _resync_current_week(session)

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(definition)
    return _view(definition)
