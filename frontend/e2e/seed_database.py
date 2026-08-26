"""Seed a scratch database for the end-to-end tests.

Run as a script, before the app starts: `python seed_database.py <db_path>`.
Not imported — it sets DATABASE_URL and the rest of the environment the app
needs before touching `app.*` at all, which only works cleanly as the first
thing a fresh process does.

Builds exactly the mix Session T's card asked the flow to be tested against:
a pending claim in the current week, one already confirmed (so a mixed batch
has something to prove nothing else moved), and a pending claim left over
from the previous week — the shape that made claims pile up unconfirmed
across a week boundary in the first place.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if len(sys.argv) != 2:
    print("usage: seed_database.py <sqlite-db-path>", file=sys.stderr)
    raise SystemExit(2)

db_path = Path(sys.argv[1]).resolve()

# Must be set before any app module is imported — app.config reads these at
# import time via get_settings(), and app.db's engine binds to DATABASE_URL
# the first time it is touched.
os.environ["CHILD_NAME"] = "E2E Kid"
os.environ["PARENT_PIN"] = "0000"
os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
os.environ["TZ"] = "Europe/London"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

config = Config(str(REPO_ROOT / "alembic.ini"))
config.set_main_option("script_location", str(REPO_ROOT / "app" / "migrations"))
command.upgrade(config, "head")

from app.config import get_settings  # noqa: E402
from app.db import create_app_engine  # noqa: E402
from app.models import (  # noqa: E402
    Cadence,
    Category,
    ChoreDefinition,
    ChoreInstance,
    InstanceState,
    Week,
)
from app.services import calendar, scheme_settings  # noqa: E402

engine = create_app_engine()
from sqlalchemy.orm import Session  # noqa: E402

with Session(engine, future=True) as session:
    beds = ChoreDefinition(
        name="Make bed", cadence=Cadence.DAILY, category=Category.BASIC, amount_pence=0
    )
    # A bonus chore that can be started today, which is what makes a make-good
    # possible at all — see wall-screen-miss.spec.ts. It adds no claim, so the
    # parent's queue is exactly what confirm-flow.spec.ts already expects.
    car = ChoreDefinition(
        name="Wash the car",
        cadence=Cadence.WEEKLY_COUNT,
        category=Category.BONUS,
        amount_pence=100,
        times_per_week=1,
    )
    session.add_all([beds, car])
    scheme_settings.get_row(session).weekly_basic_pay_pence = 200
    session.commit()

    period = calendar.current_week(get_settings().tzinfo)
    current = Week(start_date=period.start, end_date=period.end)
    previous_start = period.start.fromordinal(period.start.toordinal() - 7)
    previous_end = period.end.fromordinal(period.end.toordinal() - 7)
    previous = Week(start_date=previous_start, end_date=previous_end)
    session.add_all([current, previous])
    session.commit()

    now = datetime.now(timezone.utc)

    pending_current = ChoreInstance(
        definition_id=beds.id,
        week_id=current.id,
        due_date=period.start,
        state=InstanceState.CLAIMED,
        claimed_at=now,
    )
    confirmed_current = ChoreInstance(
        definition_id=beds.id,
        week_id=current.id,
        due_date=period.start.fromordinal(period.start.toordinal() + 1),
        state=InstanceState.CONFIRMED,
        confirmed_at=now,
        authorised_by="parent",
    )
    pending_previous = ChoreInstance(
        definition_id=beds.id,
        week_id=previous.id,
        due_date=previous_start,
        state=InstanceState.CLAIMED,
        claimed_at=now,
    )
    session.add_all([pending_current, confirmed_current, pending_previous])
    session.commit()

    print(
        "seeded:",
        "pending_current=", pending_current.id,
        "confirmed_current=", confirmed_current.id,
        "pending_previous=", pending_previous.id,
    )
