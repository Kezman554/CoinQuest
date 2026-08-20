# Project: CoinQuest

A pocket-money and chore tracker for one child, running as a self-contained service on a home Raspberry Pi.
Built with FastAPI, SQLite, Alembic, React, Vite and TypeScript, served from a single multi-stage container on port 8600.

## Structure
- `app/` - FastAPI application: models, routers, services, migrations
- `frontend/` - React + Vite + TypeScript, built into the image and served by the API
- `tests/` - pytest
- `docs/` - PRD and progress log

## Commands
- `uvicorn app.main:app --reload` - Run the API
- `npm run dev --prefix frontend` - Run the frontend against it
- `pytest` - Run tests
- `alembic upgrade head` - Apply migrations

## Git
- Do not push to GitHub without explicit permission
- Commit after completing each session
- Update docs/progress.txt briefly if significant work was done

## Conventions

These are load-bearing. Each was decided deliberately and none should be reversed without saying so.

- **Money is integer pence.** No floating point touches currency, anywhere, including in tests
- **A settled week or month is closed forever.** Amounts are stored, never recomputed. Nothing may recalculate a settled period, and no rule change reaches backwards
- **The timezone is Europe/London, set explicitly.** The container clock is UTC and every week boundary, payday and monthly period depends on getting this right
- **The child is configuration.** No child's name appears in this repository. It comes from `CHILD_NAME` at deployment. This repo is public
- **The PIN is verified server-side and rejected server-side.** Never returned to a client, never embedded in the bundle. Hiding a button is presentation, not authorisation
- **The service owns only its own database.** No external filesystem access, no dependency on any other service running
- Runs on ARM64 - anything with native builds must resolve for that architecture

## Reference
- Requirements: docs/coinquest_PRD.md
- Progress log: docs/progress.txt
- Task prompts: Kanban app
