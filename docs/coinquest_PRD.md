# CoinQuest - Product Requirements Document

Version: 0.1
Last Updated: 2026-08-20
GitHub: https://github.com/Kezman554/CoinQuest

## Overview

### Problem Statement

A household pocket-money scheme that ties chores to money only works if somebody keeps the books, and nobody does. Amounts get remembered differently by the two people involved, a savings match that rewards leaving money alone needs a balance history no one is tracking, and a child cannot see where he stands without asking. CoinQuest holds the ledger so the scheme can be run as written rather than from memory.

### Goals

- Record what was earned each week and settle it once, permanently
- Let the child see where he stands, and what he can still do about it, without asking
- Make saving visibly worthwhile through a monthly match on money left alone
- Keep a parent as the only source of truth about what was actually done
- Run unattended on a home Pi alongside the household's other services

### Target Users

One child, who claims chores and checks his progress, and his parents, who confirm the work, settle each week and pay him. Designed for a household of three around a shared kitchen screen, not for general distribution.

## Features

### Chores and claiming

- Chore definitions with five cadences: daily, n-times-per-week, week-long condition, one-off, and parent-logged event
- Categories that determine behaviour: basic chores count toward the weekly chore pay and can be missed; bonus chores pay a fixed amount all-or-nothing per week; rewards pay their own amount
- The child claims a chore; the claim is pending until a parent confirms it
- A parent may mark an instance missed directly, which is what makes the recovery window usable
- An untouched instance is provisional and becomes a miss only at settlement

### Parent actions

- Batch confirm and reject pending claims, authorised once per submission
- Record ad-hoc rewards with a free-text reason, and a preset for a recurring school award
- Waive a day, or a chore for a week, so it is never assessed; weekly-count requirements scale by days away
- Void a week, which pays nothing but still records the work done
- Settle a week, on the app's proposed figures, when the parent agrees them
- Mark a week paid, recording how much of it the child chose to deposit
- Log a withdrawal, and reconcile the recorded balance against the real account

### Settlement

- The week runs Sunday to Saturday; settlement is proposed on Sunday and never applied automatically
- More than one week may be open at a time; each settles independently on its own figures
- Missed basic chores may be recovered by completing a bonus chore unpaid, capped per week
- Recovery assignment is computed at settlement to produce the highest lawful payout, so ordering never costs the child money

### Savings

- A savings ledger recording deposits, withdrawals and an opening balance
- A monthly match on the lowest balance reached in that month, up to a capped portion of the balance
- A rate that rises with each month containing no withdrawal, and resets when one occurs
- A monthly match settled as a closed event recording the balance low, rate and cap applied

### Surfaces

- A weekly view for the child: chores, claims, misses, recovery status, and what the week is on track to pay
- A parent view carrying every action above
- A savings view, and a lifetime view contrasting actual savings with a never-withdrawn projection
- A summary endpoint shaped for an external dashboard tile: what the week is on track to pay, and whether a recovery is outstanding and by when

## Scope

### In Scope

- The weekly loop end to end: claim, confirm, settle, pay
- Chore definitions, waivers, voided weeks, ad-hoc rewards
- The earnings ledger, including the amount deposited at each payday
- The savings ledger recording deposits and the opening balance from first use
- The weekly view and the parent view
- The summary endpoint for the dashboard tile

### Out of Scope

- The savings and lifetime views, including match calculation, streak and projection
- Any second client; the app serves its own frontend and nothing else consumes it
- Tracking cash the child holds outside the savings account
- Any negative adjustment: there are no fines or deductions of any kind
- User accounts, roles or multi-tenancy; one household, one child

### Future Considerations

- The savings and lifetime views, over data recorded from day one
- A nightly export so a household assistant can answer questions when the service is unavailable
- A second parent authorised alongside the first
- Access from the child's own device, which is also when unauthenticated claiming needs revisiting

## Technical

### Stack

- Python and FastAPI: the API and all scheme logic
- SQLite: the ledgers and definitions, held in a mounted data volume
- Alembic: schema migrations, present from the first release because the savings tables arrive later
- React, Vite and TypeScript: the frontend, built and served by the same container
- Docker: a multi-stage image building the frontend and serving it alongside the API

### Integrations

- None at MVP. The service is self-contained and depends on nothing else running
- An external dashboard links to this app and reads its summary endpoint; the dependency runs one way only

### Constraints

- **Money is stored as integer pence.** Floating point is not used for currency anywhere
- **A settled week and a settled month are closed events.** Amounts are stored, never recomputed. No rule change may alter a settled period
- **The timezone is set explicitly to Europe/London.** Every week boundary, payday and monthly period depends on it, and the container clock is UTC
- **The child is configuration.** No name appears anywhere in this repository; it is supplied by environment variable at deployment
- **The authorising PIN is verified server-side only** and is never returned to, or embedded in, any client
- **No access to any external filesystem.** The service reads and writes its own database and nothing else
- Runs on ARM64 on a Raspberry Pi; the database is household data recoverable from no other source and must be included in the host's backup routine

## Project Structure

```
CoinQuest/
├── docs/
│   ├── coinquest_PRD.md
│   └── progress.txt
├── app/
│   ├── main.py
│   ├── models/
│   ├── routers/
│   ├── services/
│   └── migrations/
├── frontend/
│   ├── src/
│   └── package.json
├── tests/
├── CLAUDE.md
├── Dockerfile
├── .env.example
└── README.md
```

## Success Criteria

- [ ] A claimed chore appears as pending and only becomes confirmed once a parent authorises it
- [ ] An authorising PIN is required for every write that affects money, and is rejected by the API rather than hidden by the interface
- [ ] A batch confirmation applies completely or not at all
- [ ] A week proposes its figures, does not settle without agreement, and cannot be altered once settled
- [ ] Recovery assignment at settlement yields the highest lawful payout for the week
- [ ] A waived day or chore produces no assessable instance, and weekly counts reduce by days away as specified
- [ ] A voided week pays nothing, retains the record of work done, and leaves already-earned rewards intact
- [ ] Deposits and the opening balance are recorded from first use, before any savings feature exists
- [ ] Every monetary value in the database is an integer number of pence
- [ ] Week boundaries fall correctly during British Summer Time
- [ ] No name of a child appears anywhere in the repository
- [ ] The summary endpoint reports the week's projected pay and any outstanding recovery deadline
