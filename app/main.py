"""CoinQuest API. Serves the scheme logic and, in the container, the frontend."""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI

from app.config import get_settings
from app.routers import claims, weeks

app = FastAPI(title="CoinQuest", version="0.1.0")
app.include_router(claims.router)
app.include_router(weeks.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check, and proof the timezone resolved to the intended zone."""
    settings = get_settings()
    return {
        "status": "ok",
        "timezone": settings.timezone,
        "local_time": datetime.now(settings.tzinfo).isoformat(),
    }
