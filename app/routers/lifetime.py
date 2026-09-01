"""Lifetime totals, and the never-withdrawn comparison.

Read-only, and Oliver-facing: nothing here needs the PIN — it changes
nothing, the same as any other GET on his screens. "How money grows if you
leave it alone" is the framing this endpoint's own field name tries to
carry through to whatever reads it; see app.services.lifetime for why the
counterfactual is not "what you would have had".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.routers.dependencies import get_session
from app.services import lifetime

router = APIRouter(prefix="/api/lifetime", tags=["lifetime"])


class BalancePointView(BaseModel):
    occurred_on: str
    balance_pence: int


class SavingsBreakdownView(BaseModel):
    """Why the money in the account is there — see
    app.services.lifetime.SavingsBreakdown. Not a breakdown of
    total_earned_pence, and the three do not sum to it: this is savings-only,
    and from_match_pence in particular was never earned by anything he did."""

    from_payday_pence: int
    from_gifts_pence: int
    from_match_pence: int


class LifetimeView(BaseModel):
    total_earned_pence: int
    savings_breakdown: SavingsBreakdownView
    #: The savings balance over time exactly as it happened, withdrawals
    #: included.
    real: list[BalancePointView]
    #: What the balance would be if no withdrawal had ever happened — see
    #: app.services.lifetime.counterfactual_trajectory. Framed to a reader
    #: as "how money grows if you leave it alone", never as "what you would
    #: have had".
    counterfactual: list[BalancePointView]


def _points(values) -> list[BalancePointView]:
    return [
        BalancePointView(occurred_on=point.occurred_on.isoformat(), balance_pence=point.balance_pence)
        for point in values
    ]


@router.get("", response_model=LifetimeView)
def get_lifetime(session: Session = Depends(get_session)) -> LifetimeView:
    """Everything ever earned, the savings breakdown, and the two
    trajectories. Applies and stores nothing; every figure is recomputed
    fresh from the existing ledgers."""
    tz = get_settings().tzinfo
    breakdown = lifetime.savings_breakdown(session)
    return LifetimeView(
        total_earned_pence=lifetime.total_earned_pence(session),
        savings_breakdown=SavingsBreakdownView(
            from_payday_pence=breakdown.from_payday_pence,
            from_gifts_pence=breakdown.from_gifts_pence,
            from_match_pence=breakdown.from_match_pence,
        ),
        real=_points(lifetime.real_trajectory(session)),
        counterfactual=_points(lifetime.counterfactual_trajectory(session, tz)),
    )
