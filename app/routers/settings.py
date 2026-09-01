"""The scheme's own settings: the weekly basic pay, and the two figures a
parent reviews to change the savings-match ladder — see
app.services.savings_match for the ladder itself.

Reading needs no PIN, the same as every other GET in this API — nothing
here is sensitive, it is figures already visible elsewhere ("chore pay at
stake", a settled month's own rate). Writing does: changing any of them
reshapes what the scheme pays from here on, which is exactly the class of
thing this app requires a parent to authorise. All four fields are sent
together on every write — there is no partial update — so a saved form
always states the whole scheme, not one field layered on whatever the others
happened to be.

No re-sync on write, unlike app/routers/chores.py's writes. A chore
definition drives instances.plan_week, which materialises rows a re-sync has
to bring into line; these figures are read live — at proposal time for the
weekly basic pay, and at the next month's proposal for the ladder — and
never stored on an instance. The next GET already sees the new values; there
is nothing to bring back into line.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.routers.dependencies import AuthorisedRequest, authorise, get_session
from app.services import scheme_settings
from app.services.money import format_pence

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SchemeSettingsView(BaseModel):
    weekly_basic_pay_pence: int
    #: The same figure written out, so a screen does not reimplement £ and p.
    weekly_basic_pay: str

    #: The savings-match ladder's tunable ends — see app.services.savings_match
    #: for the ladder itself, which climbs between these by a fixed point a
    #: month and is not settable here.
    savings_match_start_rate_percent: int
    savings_match_ceiling_rate_percent: int
    savings_match_cap_pence: int
    savings_match_cap: str


class UpdateSettingsRequest(AuthorisedRequest):
    weekly_basic_pay_pence: int = Field(ge=0)
    savings_match_start_rate_percent: int = Field(ge=0, le=100)
    savings_match_ceiling_rate_percent: int = Field(ge=0, le=100)
    savings_match_cap_pence: int = Field(ge=0)

    @model_validator(mode="after")
    def the_ladder_starts_no_higher_than_it_ends(self) -> "UpdateSettingsRequest":
        if self.savings_match_start_rate_percent > self.savings_match_ceiling_rate_percent:
            raise ValueError(
                "The savings-match start rate cannot be higher than its ceiling."
            )
        return self


def _view(row) -> SchemeSettingsView:
    return SchemeSettingsView(
        weekly_basic_pay_pence=row.weekly_basic_pay_pence,
        weekly_basic_pay=format_pence(row.weekly_basic_pay_pence),
        savings_match_start_rate_percent=row.savings_match_start_rate_percent,
        savings_match_ceiling_rate_percent=row.savings_match_ceiling_rate_percent,
        savings_match_cap_pence=row.savings_match_cap_pence,
        savings_match_cap=format_pence(row.savings_match_cap_pence),
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
    """Change the scheme's settings. Takes effect from the next week or
    month proposed, never reaching back into one already closed."""
    authorise(request, body)

    row = scheme_settings.get_row(session)
    row.weekly_basic_pay_pence = body.weekly_basic_pay_pence
    row.savings_match_start_rate_percent = body.savings_match_start_rate_percent
    row.savings_match_ceiling_rate_percent = body.savings_match_ceiling_rate_percent
    row.savings_match_cap_pence = body.savings_match_cap_pence

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise

    session.refresh(row)
    return _view(row)
