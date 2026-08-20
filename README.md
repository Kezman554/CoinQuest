# CoinQuest

A pocket-money and chore tracker for one child, built to run on a home Raspberry Pi.

Chores are claimed by the child and confirmed by a parent. The week settles on a Sunday, the amount earned is recorded, and money the child chooses to save earns a monthly match that rewards leaving it alone. Nothing is ever recalculated: a settled week is a closed event, so changing a rule today cannot alter what was earned last month.

Part of a wider home-assistant stack, but it stands alone — its own service, its own database, no dependency on anything else in the house.

## Status

Early build. See `docs/coinquest_PRD.md` for the full specification and `CLAUDE.md` for how the project is laid out.

## Stack

FastAPI · SQLite · Alembic · React · Vite · TypeScript. Single multi-stage container serving the API and the built frontend.

## Running it

Copy `.env.example` to `.env` and fill it in. `CHILD_NAME` and `PARENT_PIN` have no defaults and the service will not start without them; `docs/coinquest_PRD.md` describes what each setting does.

```
python -m venv .venv && .venv/Scripts/activate   # source .venv/bin/activate on the Pi
pip install -r requirements.txt
uvicorn app.main:app --reload                     # API on :8600, /health to check it

npm install --prefix frontend
npm run dev --prefix frontend                     # dev server on :5173, proxying to the API

pytest
```

## A note on the design

Two decisions shape most of the code:

- **Money is stored as integer pence.** Never floats. A ledger that drifts by a penny is a ledger nobody trusts.
- **The child is configuration.** No name is hardcoded anywhere; it comes from the environment. The scheme's amounts, chores and rules are held as data, not as constants, because they are reviewed and changed on a schedule.
