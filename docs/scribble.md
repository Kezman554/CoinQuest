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
  data — that is the moment a bad backup is discovered too late. Session S
  (2026-08-21) shipped a second migration over the live database since this
  was written (revision 4872595d1036, the weekdays cadence) — still no
  seeded-data drill has been run. Two more have shipped since
  (a4a5f729d606, scheme_settings; 6131c9c1284a, week_reopenings), taking the
  schema from seven tables to nine. DEPLOY.md's table list is updated to
  match, but the drill itself still has not been run against seeded data —
  now across all nine tables, not the original seven. **2026-08-25 update:**
  this exact class of gap — a migration only ever exercised against an
  empty database — is what took CoinQuest down in production that day (see
  `docs/progress.txt`, Session V). The migration side of it now has a
  permanent regression test (`tests/test_migration_against_real_data.py`,
  seeds real FK-referencing rows and proves every migration from the first
  survives them); the backup-restore side, described in this paragraph,
  still has not been drilled against seeded data and remains open.

- **`4e720209aaba`'s `downgrade()` is broken the same way — found
  2026-08-27, not fixed.** Exactly the defect above, one revision lower:
  `batch_alter_table("weeks", ...)` drops `settled_base_pence` with no
  `copy_from`, Alembic reflects the live table, and the reflected CHECKs still
  name the column being dropped — `no such column: settled_base_pence`. It is
  the floor of the round-trip walk in
  `tests/test_migration_against_real_data.py` (`DOWNGRADE_FLOOR`), which is
  why that walk stops one revision above `base` instead of reaching it. Fix it
  the same way `1eb8e8b3e4ae` was fixed, then delete `DOWNGRADE_FLOOR` and
  walk the test to `"base"` — the constant exists to be removed.

- **`e42da40283c5` cannot migrate a database holding a confirmed chore
  instance — found 2026-08-27, not fixed.** It adds `authorised_by` nullable
  and a CHECK saying `state <> 'confirmed' OR authorised_by IS NOT NULL`,
  with no backfill, so any instance already in the `confirmed` state fails the
  new constraint the moment the table is rebuilt. `82826e03b64d` has the same
  shape for `missed` and `miss_origin`. Both already ran against the live
  database without incident, so this is latent rather than live — it bites a
  restore-then-migrate from a backup taken before those revisions, which is
  precisely the drill still listed as undone at the top of this file. It is
  also why the migration test seeds its settled week's instances as `claimed`
  rather than `confirmed`, noted in a comment there.

- **`1eb8e8b3e4ae`'s `downgrade()` was broken against real data — found
  2026-08-25, fixed 2026-08-27 (Session X).** Done as described below. It now
  passes `copy_from=_weeks_table()` and `recreate="always"` the way its own
  `upgrade()` and every sibling do, drops the three override CHECK constraints
  explicitly (dropping a column does not drop the constraints that mention it),
  and puts the two `weeks` immutability triggers back in their pre-revision
  shape — the revision below it downgrades to nothing, so nowhere else would
  have. Covered by `test_the_chain_walks_down_and_back_up_against_seeded_data`
  and `test_the_downgrade_leaves_the_immutability_triggers_armed`, both proved
  by reverting each half of the fix and watching the matching test fail.

- **`1eb8e8b3e4ae`'s `downgrade()` is broken against real data — found
  2026-08-25, not fixed.** Its `batch_alter_table("weeks", ...)` drops
  three columns without supplying `copy_from`, so Alembic reflects the
  live table to build the replacement and carries every CHECK constraint's
  raw SQL text along with it — including
  `ck_weeks_an_override_that_costs_money_says_why`, which mentions
  `overridden_by`, a column this same downgrade is in the middle of
  dropping. The rebuilt table's CREATE TABLE statement then names a column
  it no longer has, and SQLite refuses it: `no such column: overridden_by`.
  Every other migration that rebuilds `weeks` passes an explicit
  `copy_from=_weeks_table()` on both upgrade *and* downgrade for exactly
  this reason; this one only did it for `upgrade()`. Never caught before
  because downgrades are not part of this project's deploy story (CLAUDE.md
  and DEPLOY.md are both forward-only, applied automatically on container
  start) and nothing had ever tried to run one. Surfaced by
  `tests/test_migration_against_real_data.py` while proving the fix for the
  FK issue above, and scoped out of that test rather than fixed alongside
  it — deliberately, to keep that recovery narrow. Fix the same way every
  sibling migration already does: give `1eb8e8b3e4ae`'s downgrade an
  explicit `_weeks_table()` reflecting the pre-1eb8e8b3e4ae shape,
  `copy_from`'d the same way its `upgrade()` is.
