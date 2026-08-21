"""The week at a glance, for a tile on somebody else's dashboard.

Four rules, and they are all consequences of what reads this: a small square
on a wall panel, alongside the weather and the bins, refreshed on a timer by
something that knows nothing about this scheme.

  - **Small and stable.** Seven fields, all present every time, no nesting.
    Nothing here is optional or conditional in shape — a tile that has to
    branch on which keys arrived is a tile that breaks the week something
    changes. Only `recovery_deadline` is nullable, and it is null for exactly
    one reason: there is nothing outstanding to have a deadline.

  - **Derived from the same view the child reads**, never computed alongside
    it. If this said "recovery outstanding" while the kitchen screen said the
    week was fine, the tile would be worse than no tile. `week_view.build` is
    the single definition of what outstanding means, and this reads it.

  - **`days_remaining` is included so nobody else has to work it out.** The
    week runs Sunday to Saturday in Europe/London and contains a clock change
    twice a year; a consumer counting days from a date string gets that wrong
    once every autumn and never finds out. It is always present, whether or
    not anything is outstanding, so a tile can show how much of the week is
    left as well as how long a recovery has.

  - **Nothing about authorisation, and nothing chore-level.** No PIN state, no
    lockout state, no names, no per-chore anything. A glance does not need to
    know which chore was missed, and this endpoint is unauthenticated: what it
    returns is on a wall.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import WeekStatus
from app.models.weeks import Week
from app.services import week_view
from app.services.calendar import current_week, elapsed

#: A week nothing has happened in yet has no row, so there is nothing to
#: propose from. That is not a gap in the answer: a week in which nothing has
#: been claimed, confirmed or rewarded is worth exactly the base allowance —
#: everything untouched is a prospective miss, so the chore pay fails, and the
#: bonuses and rewards are zero. This is the figure `propose` returns for a
#: freshly opened week, not an approximation of it.
NOT_STARTED = "not_started"


@dataclass(frozen=True)
class Summary:
    """What the tile shows. Everything here is one line of text or a flag."""

    week_start: date
    week_end: date
    status: str
    projected_total_pence: int
    recovery_outstanding: bool
    recovery_deadline: date | None
    days_remaining: int


def summarise(
    session: Session, tz: tzinfo, *, now: datetime | None = None
) -> Summary:
    """This week, in the seven facts a glance needs. Writes nothing."""
    now = now or datetime.now(tz)
    period = current_week(tz)
    week = session.query(Week).filter(Week.start_date == period.start).one_or_none()

    # Whole days left, counted through `elapsed` so the week containing a clock
    # change measures the hours it actually has rather than the hours a
    # calendar assumes. Floored at zero: the last day is "0 days left", never
    # a negative.
    seconds = max(int(elapsed(now, period.ends_before).total_seconds()), 0)
    days_remaining = seconds // (24 * 60 * 60)

    if week is None:
        return Summary(
            week_start=period.start,
            week_end=period.end,
            status=NOT_STARTED,
            projected_total_pence=get_settings().weekly_base_pence,
            recovery_outstanding=False,
            recovery_deadline=None,
            days_remaining=days_remaining,
        )

    if week.status is not WeekStatus.OPEN:
        # Closed is closed: the figure is read from the week's own columns and
        # nothing about it is recomputed. There is nothing left to recover in
        # a week that has already been settled or voided.
        return Summary(
            week_start=week.start_date,
            week_end=week.end_date,
            status=week.status.value,
            projected_total_pence=week.settled_total_pence or 0,
            recovery_outstanding=False,
            recovery_deadline=None,
            days_remaining=days_remaining,
        )

    view = week_view.build(session, week, tz, now=now)
    outstanding = view.recovery.outstanding > 0

    return Summary(
        week_start=view.start_date,
        week_end=view.end_date,
        status=view.status.value,
        # The payable total: what he will actually be handed for this week,
        # rewards included. The tile is answering "how is he doing", not "what
        # figure will a parent agree to on Sunday".
        projected_total_pence=view.totals.payable_total_pence,
        recovery_outstanding=outstanding,
        recovery_deadline=view.recovery.deadline if outstanding else None,
        days_remaining=days_remaining,
    )
