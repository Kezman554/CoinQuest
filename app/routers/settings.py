"""The scheme's own settings — currently one figure, the weekly basic pay.

Reading needs no PIN, the same as every other GET in this API — nothing
here is sensitive, it is the number already visible on both screens as
"chore pay at stake". Writing does: changing it reshapes what every basic
chore is worth from the next time the week is read, which is exactly the
class of thing this app requires a parent to authorise.

No re-sync on write, unlike app/routers/chores.py's writes. A chore
definition drives instances.plan_week, which materialises rows a re-sync has
to bring into line; this figure is read live, at proposal time
(recovery.WeekAssessment.chore_pay_at_stake_pence), and never stored on an
instance. The next GET already sees the new value — there is nothing to
bring back into line.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services import scheme_settings
from app.services.money import format_pence

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SchemeSettingsView(BaseModel):
    weekly_basic_pay_pence: int
    #: The same figure written out, so a screen does not reimplement £ and p.
    weekly_basic_pay: str


class UpdateSettingsRequest(AuthorisedRequest):
    weekly_basic_pay_pence: int = Field(ge=0)


def _view(row) -> SchemeSettingsView:
    return SchemeSettingsView(
        weekly_basic_pay_pence=row.weekly_basic_pay_pence,
        weekly_basic_pay=format_pence(row.weekly_basic_pay_pence),
    )


@router.get("", response_model=SchemeSettingsView)
def get_settings_endpoint(session: Session = Depends(get_session)) -> SchemeSettingsView:
    """The scheme's settings. Reading is not authorised — see the module note."""
    return _view(scheme_settings.get_row(session))


@router.post("", response_model=SchemeSettingsView)
def update_settings(
    request: Request,
    body: UpdateSettingsRequest,
    session: Session = Depends(get_session),
) -> SchemeSettingsView:
    """Change the weekly basic pay. Takes effect the next time a week is read."""
    authorise(request, body)

    row = scheme_settings.get_row(session)
    row.weekly_basic_pay_pence = body.weekly_basic_pay_pence

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(row)
    return _view(row)
