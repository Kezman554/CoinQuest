# Scribble pad

Things not to lose track of between sessions — checked at the start of each
one, cleared as they're done. Not a task list; docs/progress.txt is the
record of what happened. This is only for things that would otherwise sit
quietly in a progress-log paragraph nobody re-reads.

## Open

- **`e42da40283c5` cannot migrate a database holding a confirmed chore
  instance — found 2026-08-27, not fixed.** It adds `authorised_by` nullable
  and a CHECK saying `state <> 'confirmed' OR authorised_by IS NOT NULL`,
  with no backfill, so any instance already in the `confirmed` state fails the
  new constraint the moment the table is rebuilt. `82826e03b64d` has the same
  shape for `missed` and `miss_origin`. Both already ran against the live
  database without incident, so this is latent rather than live — it bites a
  restore-then-migrate from a backup taken before those revisions. It is
  also why the migration test seeds its settled week's instances as `claimed`
  rather than `confirmed`, noted in a comment there.
