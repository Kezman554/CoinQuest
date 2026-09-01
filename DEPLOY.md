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
docker compose -f docker/docker-compose.yml --env-file .env up -d --build
```

`--env-file .env` is not optional here. Compose's *project directory* — where
it looks for a bare `.env` on its own — is the directory holding the `-f`
file, i.e. `docker/`, not the directory you ran the command from. Without the
flag it silently finds no `.env`, substitutes empty strings for every
`${VAR}`, and `CHILD_NAME`/`PARENT_PIN` fail closed with `set … in .env` even
though the file is sitting right there one level up. `--env-file` is resolved
relative to the working directory you run the command from, which is why this
works from the repo root and would need `--env-file ../.env` if run from
inside `docker/`.

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
docker compose -f docker/docker-compose.yml --env-file .env stop coinquest

# copy the whole volume out
docker run --rm \
  -v coinquest-data:/data \
  -v "$PWD":/backup \
  busybox tar czf /backup/coinquest-$(date +%F).tar.gz -C /data .

docker compose -f docker/docker-compose.yml --env-file .env start coinquest
```

Restore is the same in reverse, into a stopped container's volume — and doing
it once, deliberately, is the only way to know it works.

In the household stack this is automated: `scripts/coinquest-backup.sh` and
`scripts/restore-coinquest.sh` in AlfredHomeHub do the above plus rotation, an
optional offsite (restic → B2) leg, and a verification pass run inside the
app's own image (integrity check, Alembic revision, row counts across all
nine tables). See AlfredHomeHub's `DEPLOY.md` → **CoinQuest** for the nightly
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
docker compose -f docker/docker-compose.yml --env-file .env ps   # healthy only once migrations finish

curl http://localhost:8600/health          # {"status":"ok","timezone":"Europe/London",...}
curl http://localhost:8600/api/summary     # the dashboard tile's figures
curl -I http://localhost:8600/parent       # 200 text/html — SPA deep link
docker compose -f docker/docker-compose.yml --env-file .env logs -f coinquest
```

`/health` is deliberately bare and outside `/api`: a probe should not have to
know the API's layout. The compose healthcheck hits it every 30s, with a 40s
grace on first boot so migrations can finish.

## Configuration

Set in `docker/docker-compose.yml`; overridden by this repo's root `.env` —
the same one `docs/coinquest_PRD.md` and `.env.example` describe — via
`--env-file .env` on every `docker compose` command above. That flag is
load-bearing: compose's own `.env` auto-discovery looks in the directory
holding the `-f` file (`docker/`), not the directory the command is run from,
so without it every `${VAR}` in the compose file resolves empty and
`CHILD_NAME`/`PARENT_PIN` refuse to start.

| Variable | Container value | Why |
| -------- | --------------- | --- |
| `CHILD_NAME` | *(none)* | Required, no default. The child is configuration — see CLAUDE.md. |
| `PARENT_PIN` | *(none)* | Required, no default. Verified server-side only, never returned to a client. |
| `PARENT_NAMES` | *(none)* | Required, no default. Comma-separated; who the PIN may act as when posting a savings deposit directly. Adding a name is an env change, not a deploy. |
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

**Verified on the Pi, 2026-08-21** (real ARM64, not emulated). The image had
never been built before this; everything below marked done was run for real.

**The container**

- [x] Image builds; both stages resolve to `linux/arm64`.
- [x] Container starts and reaches **healthy**.
- [x] uid 1000 writes the volume.

**The app**

- [x] `/health` bare JSON; `/docs` serves Swagger.
- [x] `/` loads the app; a hard reload on a deep link serves the shell, not JSON.
- [x] `/api/summary` returns data.
- [x] An unknown `/api/*` path is a **404 `application/json`**, not the shell.
- [x] **Reachable across the LAN**, not just from the Pi itself.

**Persistence**

- [x] Data survives `compose rm -sf` and `up` (volume intact); migrations do
      not re-run against an already-current database.
- [x] Migrations ran empty → head, Alembic, no `create_all`.
- [x] Backup produces a non-empty, readable archive containing the DB.

**Backup + restore drill**

- [x] Backup → restore into a **scratch** volume → DB opens, `integrity_check`
      ok, schema at head.
- [x] **Negative test**: a deliberately corrupted or truncated archive fails
      the drill (non-zero exit) — the check has teeth rather than passing
      vacuously.
- [ ] **Still open — the gate this checklist exists for.** The drill above ran
      against an **empty** database, because that was all that existed at
      deploy time: it proves the mechanics (extract, open, integrity-check,
      restart) but not that real rows survive. Before this item can be ticked,
      seed test data across all nine tables (`chore_definitions`,
      `chore_instances`, `weeks`, `week_reopenings`, `settlement_lines`,
      `waivers`, `earnings_ledger`, `savings_ledger`, `scheme_settings`),
      back up, restore into a scratch volume, and confirm every table's row
      count comes back — the same standard KitchenSync's drill was held to
      before its backup was trusted.
