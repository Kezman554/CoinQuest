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
  seeded across every table (see `DEPLOY.md`'s current list, nine as of
  this note) before the backup can be trusted, not just proven
  mechanically. See `DEPLOY.md`'s acceptance checklist for the exact
  procedure (`scripts/restore-coinquest.sh --drill` in AlfredHomeHub) and
  `docs/progress.txt`'s 2026-08-21 addendum for the full context. Do this
  before any deploy that carries a schema migration over real household
  data — that is the moment a bad backup is discovered too late. Session O
  (2026-08-21) shipped a second migration over the live database since this
  was written (revision 4872595d1036, the weekdays cadence) — still no
  seeded-data drill has been run. Two more have shipped since
  (a4a5f729d606, scheme_settings; 6131c9c1284a, week_reopenings), taking the
  schema from seven tables to nine. DEPLOY.md's table list is updated to
  match, but the drill itself still has not been run against seeded data —
  now across all nine tables, not the original seven.
