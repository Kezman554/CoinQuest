# Deploying CoinQuest

CoinQuest runs as one container on the Pi, serving both the built app and the
API from the same origin. It is its own service in the AlfredHomeHub-style
stack:

| Port | Service |
| ---- | ------- |
| 8123 | Home Assistant |
| 8200 | Vault API |
| 8300 | Kanban board + API |
| 8400 | KitchenSync |
| 8500 | Dashboard |
| **8600** | **CoinQuest** |

Two ways to run it, sharing one Dockerfile:

- **Standalone** — `docker/docker-compose.yml` in this repo. For building,
  testing and running CoinQuest on its own.
- **In the household stack** — a `coinquest` service in AlfredHomeHub's
  `docker/docker-compose.yml`, built from this repo cloned as a sibling. See
  AlfredHomeHub's `DEPLOY.md` for that route; this file covers the standalone
  one and everything both routes share.

## Mounts: one, deliberately

CoinQuest mounts **only its data volume**. No vault clone, no SSH key, no
`/etc/localtime` — see CLAUDE.md: "the service owns only its own database. No
external filesystem access, no dependency on any other service running." `TZ`
is enough on its own, because every date the app computes goes through
`Europe/London` explicitly (`app/services/calendar.py`), never the container
or host clock.

## The deploy (standalone)

Authoring happens on the laptop; the Pi only pulls.

```bash
# on the laptop
git push

# on the Pi
cd ~/projects/CoinQuest
git pull
docker compose -f docker/docker-compose.yml up -d --build
```

That is the whole thing. Migrations run on startup — see the caveat below
before the *first* build over real data.

Reach it at `http://<pi>:8600/`.

## ⚠️ Backups

Migrations apply automatically on every container start (`app/main.py`'s
lifespan runs `alembic upgrade head` before the app serves a request). That is
what makes deploying one command, and it is why backups matter more here than
the frequency of schema changes suggests.

**The initial deploy is not the risky one.** It migrates an empty database —
there are no rows to lose. What the backup actually protects is:

1. **Every later migration**, once there is real data in it. Take a fresh
   snapshot immediately before each one.
2. **The data itself.** A settled week's figures are stored, never
   recomputed, and the earnings and savings ledgers are append-only — nothing
   here can be rebuilt from the scheme's rules if it is lost. None of it is in
   git.

So: set the backup up **at** deploy, while it costs nothing and nothing is at
stake. Then **prove the restore works once real data exists** — an untested
backup is a belief, not a safety net, and the moment you need it is the worst
moment to discover the tar was empty or the permissions were wrong.

```bash
# stop the app so nothing writes mid-copy
docker compose -f docker/docker-compose.yml stop coinquest

# copy the whole volume out
docker run --rm \
  -v coinquest-data:/data \
  -v "$PWD":/backup \
  busybox tar czf /backup/coinquest-$(date +%F).tar.gz -C /data .

docker compose -f docker/docker-compose.yml start coinquest
```

Restore is the same in reverse, into a stopped container's volume — and doing
it once, deliberately, is the only way to know it works.

In the household stack this is automated: `scripts/coinquest-backup.sh` and
`scripts/restore-coinquest.sh` in AlfredHomeHub do the above plus rotation, an
optional offsite (restic → B2) leg, and a verification pass run inside the
app's own image (integrity check, Alembic revision, row counts across all
seven tables). See AlfredHomeHub's `DEPLOY.md` → **CoinQuest** for the nightly
cron slot and the full drill.

## What must survive

One file, on a volume:

| Path | Holds | Recoverable from git? |
| ---- | ----- | --------------------- |
| `/data/coinquest.db` | chores, claims, settled weeks, the earnings ledger, the savings ledger | **No** |

By default this is a named volume, `coinquest-data`. To use a host directory
instead — easier to back up with ordinary tools — set `COINQUEST_DATA_PATH`:

```bash
COINQUEST_DATA_PATH=/home/kezman554/coinquest-data
```

It must be writable by uid 1000, the container's user.

## Architecture

The Pi is ARM64. Both base images are multi-arch, so building **on the Pi**
(the command above) needs nothing special.

To build on the laptop instead, cross-build explicitly — a plain `docker
build` there produces an amd64 image that will not run on the Pi:

```bash
docker buildx build --platform linux/arm64 -t coinquest:latest --load .
```

## Checking it

```bash
docker compose -f docker/docker-compose.yml ps   # healthy only once migrations finish

curl http://localhost:8600/health          # {"status":"ok","timezone":"Europe/London",...}
curl http://localhost:8600/api/summary     # the dashboard tile's figures
curl -I http://localhost:8600/parent       # 200 text/html — SPA deep link
docker compose -f docker/docker-compose.yml logs -f coinquest
```

`/health` is deliberately bare and outside `/api`: a probe should not have to
know the API's layout. The compose healthcheck hits it every 30s, with a 40s
grace on first boot so migrations can finish.

## Configuration

Set in `docker/docker-compose.yml`; override in a `.env` beside it (this
repo's root `.env`, the same one `docs/coinquest_PRD.md` and `.env.example`
describe — compose reads it automatically when invoked from the repo root).

| Variable | Container value | Why |
| -------- | --------------- | --- |
| `CHILD_NAME` | *(none)* | Required, no default. The child is configuration — see CLAUDE.md. |
| `PARENT_PIN` | *(none)* | Required, no default. Verified server-side only, never returned to a client. |
| `DATABASE_URL` | `sqlite:////data/coinquest.db` | Absolute. A relative path resolves against the working directory and dies with the container. |
| `TZ` | `Europe/London` | Every week boundary, payday and monthly period depends on this. The container clock is UTC. |
| `FRONTEND_DIR` | `/app/frontend_dist` | The built bundle, served at `/`. Baked into the image; not meant to be overridden at deploy time. |

## What is served where

- `/` — the built app. Unknown paths fall back to `index.html`, so deep links
  and hard reloads work.
- `/api/*` — the data API. An unknown path here is a **404**, not the app
  shell: an integration client must never receive HTML to parse as JSON.
- `/health`, `/docs`, `/openapi.json` — at the root.

## Deploy acceptance

Not yet run for real. The checklist below is what a first deploy on the Pi
needs to clear before this file can say it happened, mirroring the drill
KitchenSync's `DEPLOY.md` records — copy that structure here once it is done.

**The container**

- [ ] Image builds; both stages resolve to `linux/arm64`.
- [ ] Container starts and reaches **healthy**.
- [ ] uid 1000 writes the volume.

**The app**

- [ ] `/health` bare JSON; `/docs` serves Swagger.
- [ ] `/` loads the app; a hard reload on a deep link serves the shell, not JSON.
- [ ] `/api/summary` returns data.
- [ ] An unknown `/api/*` path is a **404 `application/json`**, not the shell.
- [ ] Reachable across the LAN, not just from the Pi itself.

**Persistence**

- [ ] Data survives `compose rm -sf` and `up` (volume intact); migrations do
      not re-run against an already-current database.
- [ ] Migrations ran empty → head, Alembic, no `create_all`.
- [ ] Backup produces a non-empty, readable archive containing the DB.

**Backup + restore drill — the gate**

- [ ] Test data across all seven tables → backup → restore into a **scratch**
      volume → DB opens, `integrity_check` ok, schema at head, rows present
      everywhere expected.
- [ ] **Negative test**: a deliberately corrupted or truncated archive fails
      the drill (non-zero exit) — the check has teeth rather than passing
      vacuously.
