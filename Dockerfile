# CoinQuest — one container serving the built React app and the API together.
#
# Built for the Pi (ARM64). Both stages use multi-arch base images, so
# `docker buildx build --platform linux/arm64` from a laptop and a plain
# `docker compose build` on the Pi produce the same thing.

# ---------------------------------------------------------------------------
# Stage 1 — build the bundle
# ---------------------------------------------------------------------------
# node:24 ships npm 11, matching the npm that owns frontend/package-lock.json.
# An older major can resolve the same lockfile differently and fail `npm ci`
# on a transitive it locked to a range npm 11 pins more tightly. Keep this in
# step with whatever npm regenerates the lockfile.
FROM node:24-bookworm-slim AS frontend

WORKDIR /build

# Dependencies first, so editing source does not re-run the install layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — the runtime
# ---------------------------------------------------------------------------
# PINNED to a Debian release, not :slim or :latest, so the SQLite version this
# ships is deliberate rather than whatever happened to be current on the day
# of a rebuild. Bookworm's SQLite comfortably clears Alembic's batch-mode
# migration requirements.
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the migrations that own the schema.
COPY app/ ./app/
COPY alembic.ini ./

# The built bundle, served at / by FastAPI (see app/frontend.py).
COPY --from=frontend /build/dist ./frontend_dist

# Absolute paths inside the container. DATABASE_URL's directory is the mount
# point for the data volume: nothing under it survives a rebuild unless it is
# on that volume. TZ is set explicitly here rather than inherited, because the
# container clock is UTC and every week boundary, payday and monthly period
# depends on getting this right — see app/config.py and app/services/calendar.py.
ENV FRONTEND_DIR=/app/frontend_dist \
    DATABASE_URL=sqlite:////data/coinquest.db \
    TZ=Europe/London

# Created so the volume mounts onto a real directory.
RUN mkdir -p /data

# Runs as a non-root user; the volume must be writable by it. This service
# reads no filesystem but its own database — no other mount is ever added.
RUN useradd --create-home --uid 1000 coinquest \
    && chown -R coinquest:coinquest /app /data
USER coinquest

EXPOSE 8600

# Migrations run on startup (see app/main.py's lifespan), so `docker compose
# up` after a pull applies them — there is no separate step to forget.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
