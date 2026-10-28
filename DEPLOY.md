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
`${VAR}`, and `CHILD_NAME` and the parents fail closed with `set … in .env` even
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
eleven tables, and the stored figures compared row by row against live). See AlfredHomeHub's `DEPLOY.md` → **CoinQuest** for the nightly
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

## Moving from one PIN to named parents

Before parents had names, one `PARENT_PIN` authorised everything and every
record said "parent". Now each parent has their own name and PIN, and the
image refuses to start with the old variables still set. The change is three
things done together — `.env`, compose file, new image — because the old
image needs `PARENT_PIN` and the new one refuses it:

1. In `.env`: add `PARENT_1_NAME`, `PARENT_1_PIN` (the old PIN can be reused
   here), optionally `PARENT_2_NAME` / `PARENT_2_PIN`, and `BANK_HOLDER`.
   Delete the `PARENT_PIN` and `PARENT_NAMES` lines.
2. In the compose file: the same variables passed through (this repo's
   `docker/docker-compose.yml` already does; in the household stack, the
   `coinquest` service in AlfredHomeHub's `docker/docker-compose.yml`).
3. Pull and rebuild CoinQuest.

Nothing in the database changes: rows already recorded keep "parent" (the
tables are append-only), and the parent view shows them as "a parent". New
rows carry the acting parent's name.

## Configuration

Set in `docker/docker-compose.yml`; overridden by this repo's root `.env` —
the same one `docs/coinquest_PRD.md` and `.env.example` describe — via
`--env-file .env` on every `docker compose` command above. That flag is
load-bearing: compose's own `.env` auto-discovery looks in the directory
holding the `-f` file (`docker/`), not the directory the command is run from,
so without it every `${VAR}` in the compose file resolves empty and
`CHILD_NAME` and the parents refuse to start.

| Variable | Container value | Why |
| -------- | --------------- | --- |
| `CHILD_NAME` | *(none)* | Required, no default. The child is configuration — see CLAUDE.md. |
| `PARENT_1_NAME` / `PARENT_1_PIN` | *(none)* | Required, no default. A parent's display name and their own PIN. The PIN is verified server-side only, never returned to a client, and proves which parent is acting: the name is what is recorded and what the parent view shows. |
| `PARENT_2_NAME` / `PARENT_2_PIN` | *(empty)* | Optional: a second parent, the same shape. Both empty means there is none; one empty refuses to start. Parents may not share a PIN or a name; names are at most 60 characters. |
| `BANK_HOLDER` | *(none)* | Required, no default. The number (`1` or `2`) of the parent who pays the savings match into the bank. Settling the monthly interest is refused for any other parent; everything else is open to all of them. |
| ~~`PARENT_PIN`~~, ~~`PARENT_NAMES`~~ | — | **Retired. Remove both from `.env`.** The service refuses to start while either is set, so an old PIN cannot linger. `PARENT_PIN` becomes `PARENT_1_PIN`; `PARENT_NAMES` becomes the `PARENT_n_NAME` lines. |
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
- [x] **Real rows come back from B2 — done 2026-10-28.** The drill above ran
      against an **empty** database, because that was all that existed at
      deploy time: it proved the mechanics (extract, open, integrity-check,
      restart) but not that real rows survive. On 2026-10-28, after the first
      monthly savings match settled (September, 50p), a fresh backup went to
      B2 as snapshot `6d594818` (`coinquest-2026-10-28-1039.tar.gz`) and
      `restore-coinquest.sh --drill --snapshot 6d594818` restored it into the
      scratch volume `coinquest-restore-drill`, live untouched:
      `integrity_check` ok, schema at head `8a5d83828968`, `RESTORE VERIFIED`,
      exit 0. Compared against live:
      - **Row counts, all eleven tables, every one equal**:
        `chore_definitions` 6, `chore_instances` 183, `weeks` 11,
        `settlement_lines` 28, `waivers` 4, `earnings_ledger` 7,
        `savings_ledger` 2, `week_reopenings` 0, `savings_month_matches` 1,
        `savings_deposit_requests` 1, `scheme_settings` 1.
      - **Row by row, every column identical**: `savings_month_matches` (its
        first comparison against a real row — 11 columns), `settlement_lines`,
        both ledgers; and the stored closing and payment figures of all ten
        closed weeks.
      - **Made to fail on purpose**: a scratch copy of the same archive with
        the match's triggers dropped and its row moved to low 10000p / match
        500p (moved together, because the table's CHECK refuses a match that
        is not the rate applied to the capped low) still passed
        `integrity_check` and matched on count, and the drill exited 1 on
        `savings_month_matches id 1: restored (...) != live (...)`.
- [ ] **`week_reopenings` is still empty in live** (0 against 0 on
      2026-10-28 and on every earlier drill), so no reopening has ever come
      back from B2. Not to be filled by creating one: re-run the B2 drill the
      first time a week is genuinely reopened.
