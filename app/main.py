"""CoinQuest API. Serves the scheme logic and, in the container, the frontend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI

from app.config import get_settings
from app.db import run_migrations
from app.frontend import mount_frontend
from app.routers import (
    chores,
    claims,
    lifetime,
    parent,
    rewards,
    savings_match,
    settings as settings_router,
    summary,
    waivers,
    week_view,
    weeks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Applies pending migrations on boot, so `docker compose up` after a pull
    # is the whole deploy — there is no separate step to forget. Idempotent,
    # so re-running it here against an already-migrated test database is a
    # no-op.
    run_migrations()
    yield


app = FastAPI(title="CoinQuest", version="0.1.0", lifespan=lifespan)
app.include_router(chores.router)
app.include_router(claims.router)
app.include_router(weeks.router)
app.include_router(weeks.savings_router)
app.include_router(savings_match.router)
app.include_router(lifetime.router)
app.include_router(rewards.router)
app.include_router(week_view.router)
app.include_router(parent.router)
app.include_router(waivers.router)
app.include_router(summary.router)
app.include_router(settings_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check, and proof the timezone resolved to the intended zone."""
    settings = get_settings()
    return {
        "status": "ok",
        "timezone": settings.timezone,
        "local_time": datetime.now(settings.tzinfo).isoformat(),
    }


# LAST, because it matches every remaining path. Every API route and /health
# are already registered, so none of them can be shadowed. A no-op when there
# is no built bundle, which is how dev and the test suite run.
mount_frontend(app, get_settings().frontend_dir)
