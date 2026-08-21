"""GET /api/summary — the week in one small, stable object.

Unauthenticated, because it is read by a dashboard tile that has no
credential and should never be given one. It carries nothing that a PIN would
protect: no authorisation state, no lockout state, no chore names, no
per-chore anything. A glance needs a figure, a flag and a date.

The shape is a contract with something outside this repository. Fields may be
added; the seven here keep their names and their types.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.routers.dependencies import get_session
from app.services import summary
from app.services.money import format_pence

router = APIRouter(prefix="/api/summary", tags=["summary"])


class SummaryView(BaseModel):
    week_start: str
    week_end: str
    status: str

    #: What this week is on track to be worth, rewards included.
    projected_total_pence: int
    #: The same figure written out, so a tile does not reimplement £ and p.
    projected_total: str

    recovery_outstanding: bool
    #: The last day a recovery can be worked. Null when nothing is outstanding.
    recovery_deadline: str | None
    #: Whole days left in the week, always present.
    days_remaining: int


@router.get("", response_model=SummaryView)
def get_summary(session: Session = Depends(get_session)) -> SummaryView:
    """This week's projected total, and whether anything is outstanding."""
    result = summary.summarise(session, get_settings().tzinfo)
    return SummaryView(
        week_start=result.week_start.isoformat(),
        week_end=result.week_end.isoformat(),
        status=result.status,
        projected_total_pence=result.projected_total_pence,
        projected_total=format_pence(result.projected_total_pence),
        recovery_outstanding=result.recovery_outstanding,
        recovery_deadline=(
            result.recovery_deadline.isoformat() if result.recovery_deadline else None
        ),
        days_remaining=result.days_remaining,
    )
