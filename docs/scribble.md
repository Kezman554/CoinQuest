# Scribble pad

Things not to lose track of between sessions — checked at the start of each
one, cleared as they're done. Not a task list; docs/progress.txt is the
record of what happened. This is only for things that would otherwise sit
quietly in a progress-log paragraph nobody re-reads.

## Open

- **Run the seeded-data restore drill before the first real migration.**
  The restore drill verified on the Pi on 2026-08-21 only proved the
  mechanics (extract, open, integrity-check, restart) against an **empty**
  database — that was all that existed. It still needs a real run with data
  seeded across all seven tables (`chore_definitions`, `chore_instances`,
  `weeks`, `settlement_lines`, `waivers`, `earnings_ledger`,
  `savings_ledger`) before the backup can be trusted, not just proven
  mechanically. See `DEPLOY.md`'s acceptance checklist for the exact
  procedure (`scripts/restore-coinquest.sh --drill` in AlfredHomeHub) and
  `docs/progress.txt`'s 2026-08-21 addendum for the full context. Do this
  before any deploy that carries a schema migration over real household
  data — that is the moment a bad backup is discovered too late.

- **"Specific weekdays" as a chore cadence is not built.** Deferred on
  2026-08-21 when adding the chore-management screen (Session N): every real
  chore in pocket-money-rules.md is daily, N-times-a-week or week-long, so
  the five existing cadences cover the actual scheme, and a chore fixed to
  particular weekdays (e.g. "bins out Tue/Fri") isn't used by anything today.
  If it's wanted later it needs a new `Cadence` member, a column for which
  weekdays, a branch in `instances.plan_week` (day-scoped, like DAILY but
  filtered — week_view.py's day/week grouping already keys off `due_date`
  rather than cadence, so that part is free), and a decision on whether it
  belongs in `WEEK_DERIVED_CADENCES` and `ON_DEMAND_CADENCES` — see
  app/services/recovery.py. Don't add it as just a form option without that
  engine work: a chore that's created but never generates an instance is a
  real-money bug wearing a UI.
