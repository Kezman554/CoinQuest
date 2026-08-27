"""Every migration has to survive a database that already has real rows in it.

2026-08-25: a deploy against the real household database failed. A migration
that rebuilds `weeks` — SQLite's only way to change a CHECK or a trigger,
which several migrations in this project's history have needed — drops the
table as part of that rebuild, and SQLite refuses to drop a table that
another table's row still references with `ON DELETE RESTRICT` while foreign
key enforcement is on. The household's `chore_instances` already had rows
pointing at real weeks, because a chore had actually been claimed. Nothing
in the rest of this suite could have caught that: every other fixture here
(`migrated_database`, `session`) migrates a database that starts, and stays,
empty. `docs/scribble.md` had already flagged that backups were never
drilled against seeded data; this is the same gap on the migration side, and
this file exists so it does not stay open a second time.

The fix lives in app/migrations/env.py — SQLite only honours
`PRAGMA foreign_keys=OFF` with no transaction pending, and Alembic opens a
real one around each migration script for a dialect that cannot run DDL
transactionally, so the pragma has to be toggled on the raw connection
before Alembic touches it, not from inside a migration.

This test seeds every table that exists straight after the very first
migration — before any later migration has had the chance to rebuild
anything — with real rows that reference each other exactly as production
data does, then runs every remaining migration in one call to
`app.db.run_migrations()`, the same function `app.main`'s startup lifespan
calls. That is deliberate: an earlier manual check of this fix ran plain
`alembic upgrade head` directly and it passed even against the *unfixed*
`env.py`, because that path never imports `app.db` and so never turns
foreign keys on in the first place — only going through the real function
reproduces what a real deploy does.

Whatever migration is newest when this runs is the one actually being
proved, but nothing here names it: the base and head revisions are read from
the migration scripts themselves, so this stays a permanent, self-updating
regression test rather than a one-off check for the 2026-08-25 incident.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _config(database_url: str):
    from alembic.config import Config

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _seed_real_data(db_path: Path) -> dict[str, int]:
    """Insert one realistic, FK-referencing row into every table that exists
    straight after the initial migration, with foreign keys enforced while
    doing it — the same guarantee production runs under.

    Only columns present since that very first migration are named
    explicitly, and only where a value is required: a column added or
    renamed by a later migration is left to its default or NULL, which is
    valid at every point in the chain including this one. That is what lets
    this seed the schema as it stood at the very start of the project's
    history without needing to know what any later migration did to it.

    Returns the row count seeded per table, so the caller can confirm
    afterwards that nothing was lost.
    """
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=ON")

        con.execute(
            "INSERT INTO chore_definitions"
            " (id, name, cadence, category, amount_pence, is_available,"
            "  created_at, updated_at)"
            " VALUES (1, 'Make bed', 'daily', 'basic', 0, 1,"
            "  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO weeks (id, start_date, end_date, status, created_at)"
            " VALUES (1, '2026-08-16', '2026-08-22', 'open', CURRENT_TIMESTAMP)"
        )
        # A settled week as well as an open one. A rebuild of `weeks` has to
        # carry a closed week's stored figures across intact and satisfy the
        # closed-week CHECK on the far side, and the two immutability triggers
        # only have anything to say about a row in this state — an open week
        # would let a disarmed trigger pass unnoticed.
        con.execute(
            "INSERT INTO weeks (id, start_date, end_date, status,"
            "  settled_basic_pence, settled_bonus_pence, settled_reward_pence,"
            "  settled_total_pence, closed_at, created_at)"
            " VALUES (2, '2026-08-09', '2026-08-15', 'settled',"
            "  250, 50, 0, 300, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )

        # Seven real chore_instances, one per day of the week — exactly the
        # shape of row that blocked the real deploy: each references the
        # week above with ON DELETE RESTRICT.
        for day in range(16, 23):
            con.execute(
                "INSERT INTO chore_instances"
                " (definition_id, week_id, due_date, state, quantity, created_at)"
                " VALUES (1, 1, ?, 'untouched', 1, CURRENT_TIMESTAMP)",
                (f"2026-08-{day:02d}",),
            )

        # Claimed, not confirmed or missed: both of those states acquired a
        # CHECK later in the chain (`authorised_by`, `miss_origin`) naming a
        # column that does not exist here yet and that no migration backfills,
        # so a row seeded in either state would be rejected on the way up by a
        # constraint about authorship rather than by anything this file is
        # testing. Noted in docs/scribble.md; a claimed instance references the
        # settled week under ON DELETE RESTRICT just as firmly.
        for day in range(9, 16):
            con.execute(
                "INSERT INTO chore_instances"
                " (definition_id, week_id, due_date, state, quantity,"
                "  claimed_at, created_at)"
                " VALUES (1, 2, ?, 'claimed', 1, CURRENT_TIMESTAMP,"
                "  CURRENT_TIMESTAMP)",
                (f"2026-08-{day:02d}",),
            )

        # One row in every other table that references a week, so a future
        # migration rebuilding any of them is proved against real data too —
        # not only the table that actually broke this time.
        con.execute(
            "INSERT INTO earnings_ledger"
            " (id, entry_type, amount_pence, week_id, occurred_on, reason, created_at)"
            " VALUES (1, 'week_settlement', 100, 1, '2026-08-22', 'seed', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO earnings_ledger"
            " (id, entry_type, amount_pence, week_id, occurred_on, reason, created_at)"
            " VALUES (2, 'week_settlement', 300, 2, '2026-08-15', 'seed',"
            "  CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO savings_ledger"
            " (id, entry_type, amount_pence, balance_after_pence, occurred_on, created_at)"
            " VALUES (1, 'opening_balance', 100, 100, '2026-08-16', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO savings_ledger"
            " (id, entry_type, amount_pence, balance_after_pence, week_id,"
            "  occurred_on, created_at)"
            " VALUES (2, 'deposit', 300, 400, 2, '2026-08-15', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO settlement_lines"
            " (id, week_id, chore_name, category, cadence, unit_amount_pence,"
            "  quantity, amount_pence, created_at)"
            " VALUES (1, 1, 'Make bed', 'basic', 'daily', 0, 1, 0, CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO settlement_lines"
            " (id, week_id, chore_name, category, cadence, unit_amount_pence,"
            "  quantity, amount_pence, created_at)"
            " VALUES (2, 2, 'Make bed', 'basic', 'daily', 50, 5, 250,"
            "  CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO waivers (id, scope, day, created_at)"
            " VALUES (1, 'day', '2026-08-30', CURRENT_TIMESTAMP)"
        )

        con.commit()

        counts = {}
        for table in (
            "chore_definitions",
            "weeks",
            "chore_instances",
            "earnings_ledger",
            "savings_ledger",
            "settlement_lines",
            "waivers",
        ):
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return counts
    finally:
        con.close()


def test_every_migration_from_the_first_survives_real_referencing_rows(
    tmp_path, monkeypatch
):
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "seeded.db"
    url = f"sqlite:///{db_path.as_posix()}"

    # env.py always re-reads get_settings().database_url and overrides
    # whatever URL is set directly on the Config object with it — so this has
    # to be in place before the *first* alembic call, not only before the
    # one that matters, or command.upgrade() silently migrates whatever
    # database the environment already pointed at.
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()

    config = _config(url)
    script = ScriptDirectory.from_config(config)
    (base,) = script.get_bases()  # one root: this project has no branches
    head = script.get_current_head()
    assert base != head, "nothing to prove if there is only one migration"

    try:
        # Stage 1: just the foundational tables, nothing rebuilt yet.
        command.upgrade(config, base)

        seeded = _seed_real_data(db_path)
        assert seeded == {
            "chore_definitions": 1,
            "weeks": 2,
            "chore_instances": 14,
            "earnings_ledger": 2,
            "savings_ledger": 2,
            "settlement_lines": 2,
            "waivers": 1,
        }, seeded

        # Stage 2: every remaining migration, through app.db.run_migrations()
        # — the same function app.main's startup lifespan calls, and the
        # only path that actually turns foreign keys on the way a real
        # deploy does (see this module's docstring for why that distinction
        # is the whole test).
        from app.db import run_migrations

        run_migrations()
    finally:
        get_settings.cache_clear()

    con = sqlite3.connect(str(db_path))
    try:
        (version,) = con.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == head

        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []

        # Every seeded row is still there — a migration that "succeeded" by
        # silently dropping data would be worse than one that fails loudly.
        for table, expected in seeded.items():
            (count,) = con.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert count == expected, f"{table}: expected {expected}, found {count}"
    finally:
        con.close()


def test_the_newest_migration_downgrades_cleanly_against_seeded_data(
    tmp_path, monkeypatch
):
    """Only the newest migration's own downgrade, one step back from head.

    Whatever migration is newest gets its downgrade run against seeded data
    the moment it lands, without anyone having to remember to. The longer
    walk — every downgrade the chain can currently run, and back up again —
    is the test below.
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "seeded.db"
    url = f"sqlite:///{db_path.as_posix()}"

    # See the sibling test above: this has to be set before the first
    # alembic call, not only before the one that matters.
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()

    config = _config(url)
    script = ScriptDirectory.from_config(config)
    (base,) = script.get_bases()

    try:
        command.upgrade(config, base)
        _seed_real_data(db_path)

        from app.db import run_migrations

        run_migrations()

        command.downgrade(config, "-1")
    finally:
        get_settings.cache_clear()


# The floor of the round-trip walk below, and the reason it is not `base`.
#
# `4e720209aaba`'s own downgrade has the same defect `1eb8e8b3e4ae`'s had and
# Session X fixed: it drops `settled_base_pence` through a `batch_alter_table`
# with no `copy_from`, so Alembic reflects the live table to build the
# replacement and the reflected CHECKs still name the column being dropped —
# `no such column: settled_base_pence`. Fixing a second historical migration
# was not that session's remit, so the walk stops on top of it rather than
# pretending the step below works. Logged in docs/scribble.md. When that one
# is fixed, delete this constant and walk to "base".
DOWNGRADE_FLOOR = "4e720209aaba"


def _revision_chain(script) -> list[str]:
    """Every revision, base first, head last."""
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


def _walk_down_to_the_floor(config, chain: list[str]) -> None:
    """One revision at a time, so a failure names the step that broke it
    rather than only the range that contains it."""
    from alembic import command

    floor = chain.index(DOWNGRADE_FLOOR)
    assert floor > 0, "the floor is not in the chain; has a revision been renamed?"
    for target in range(len(chain) - 2, floor - 1, -1):
        command.downgrade(config, chain[target])


def _weeks_triggers(con) -> dict[str, str]:
    return dict(
        con.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'weeks'"
        ).fetchall()
    )


def _assert_the_week_is_closed_forever(con, week_id: int) -> None:
    """The two immutability guarantees, proved by trying to break them.

    Asserting the triggers merely exist proves only that something with the
    right name is in sqlite_master; a rebuild that recreated them against the
    wrong column list would pass that too. These two statements are what a
    downgrade must never quietly start allowing.
    """
    with pytest.raises(sqlite3.IntegrityError, match="closed forever"):
        con.execute(
            "UPDATE weeks SET settled_total_pence = 999 WHERE id = ?", (week_id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        con.execute("DELETE FROM weeks WHERE id = ?", (week_id,))


def test_the_chain_walks_down_and_back_up_against_seeded_data(tmp_path, monkeypatch):
    """Down every downgrade the chain can run, and back up, on real rows.

    The sibling tests above only go up. This one goes up, then down, then up
    again, and the down leg is where the interesting failures live: rebuilding
    a table means dropping it, and SQLite refuses to drop a table another
    table's rows still reference under ON DELETE RESTRICT. That is the same
    shape of failure as the 2026-08-25 incident, and it is why every rebuild
    in this project has passed at first deploy and failed in anger.

    Seeded from real-shaped data rather than an empty database: a settled week
    carrying its stored figures, an open week, entries in both ledgers,
    settlement lines, and fourteen chore_instances pointing at the two weeks.
    An empty database has no rows to refuse to drop and no closed row for a
    trigger to have an opinion about, so it proves nothing either way.

    Driven through `app.db.run_migrations()` on both up legs rather than a
    plain `alembic upgrade` — see this module's docstring: the CLI path never
    imports `app.db`, so it never turns foreign keys on, and would pass on a
    database the app itself cannot migrate.
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "seeded.db"
    url = f"sqlite:///{db_path.as_posix()}"

    # See the sibling tests: this has to be in place before the *first*
    # alembic call, not only before the one that matters.
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()

    config = _config(url)
    script = ScriptDirectory.from_config(config)
    (base,) = script.get_bases()
    head = script.get_current_head()
    chain = _revision_chain(script)
    assert chain[0] == base and chain[-1] == head, chain

    try:
        command.upgrade(config, base)
        seeded = _seed_real_data(db_path)

        from app.db import run_migrations

        run_migrations()
        _walk_down_to_the_floor(config, chain)
        run_migrations()
    finally:
        get_settings.cache_clear()

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=ON")

        (version,) = con.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == head

        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []

        for table, expected in seeded.items():
            (count,) = con.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert count == expected, f"{table}: expected {expected}, found {count}"

        # The settled week came back with its figures untouched. A round trip
        # that quietly alters a closed week's stored amounts has broken the one
        # rule this schema exists to keep.
        assert con.execute(
            "SELECT settled_chore_pay_pence, settled_bonus_pence,"
            " settled_reward_pence, settled_total_pence, status"
            " FROM weeks WHERE id = 2"
        ).fetchone() == (250, 50, 0, 300, "settled")

        _assert_the_week_is_closed_forever(con, week_id=2)
    finally:
        con.close()


def test_the_downgrade_leaves_the_immutability_triggers_armed(tmp_path, monkeypatch):
    """A downgrade that disarms the guarantee is worse than one that refuses.

    `1eb8e8b3e4ae` drops the two `weeks` triggers at the top of its downgrade,
    because the rebuild underneath cannot happen while they are attached. The
    revision below it downgrades to nothing at all, so if that downgrade does
    not put them back, nothing does: the database would sit one revision back
    from head with a settled week's figures freely editable and a closed week
    freely deletable, and nothing anywhere saying so. This asserts the state
    the database is actually left in at the bottom of the walk.
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    db_path = tmp_path / "seeded.db"
    url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()

    config = _config(url)
    script = ScriptDirectory.from_config(config)
    (base,) = script.get_bases()
    chain = _revision_chain(script)

    try:
        command.upgrade(config, base)
        _seed_real_data(db_path)

        from app.db import run_migrations

        run_migrations()
        _walk_down_to_the_floor(config, chain)
    finally:
        get_settings.cache_clear()

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=ON")

        triggers = _weeks_triggers(con)
        assert set(triggers) == {
            "settled_week_figures_are_final",
            "a_closed_week_is_not_deleted",
        }, triggers

        # And restored in the shape this point in the chain calls for: the
        # three override columns are gone by now, so the trigger must not name
        # them — a trigger naming a dropped column raises an error about the
        # column instead of guarding anything.
        final = triggers["settled_week_figures_are_final"]
        for column in ("overridden_by", "override_reason", "optimum_total_pence"):
            assert column not in final, column
        assert "settled_total_pence" in final

        _assert_the_week_is_closed_forever(con, week_id=2)
    finally:
        con.close()
