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

        # One row in every other table that references a week, so a future
        # migration rebuilding any of them is proved against real data too —
        # not only the table that actually broke this time.
        con.execute(
            "INSERT INTO earnings_ledger"
            " (id, entry_type, amount_pence, week_id, occurred_on, reason, created_at)"
            " VALUES (1, 'week_settlement', 100, 1, '2026-08-22', 'seed', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO savings_ledger"
            " (id, entry_type, amount_pence, balance_after_pence, occurred_on, created_at)"
            " VALUES (1, 'opening_balance', 100, 100, '2026-08-16', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO settlement_lines"
            " (id, week_id, chore_name, category, cadence, unit_amount_pence,"
            "  quantity, amount_pence, created_at)"
            " VALUES (1, 1, 'Make bed', 'basic', 'daily', 0, 1, 0, CURRENT_TIMESTAMP)"
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
        assert seeded["chore_instances"] == 7, seeded
        assert all(
            count == 1 for table, count in seeded.items() if table != "chore_instances"
        ), seeded

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

    Not a walk all the way to the base: downgrading through this project's
    full history hits at least one unrelated, pre-existing problem
    (1eb8e8b3e4ae's downgrade rebuilds `weeks` without supplying an explicit
    target shape, so Alembic reflects the live table and carries a CHECK
    constraint referencing a column the same rebuild just dropped — a real
    bug, but not this one, never previously exercised because downgrades
    are not part of this project's deploy story, and out of scope for the
    incident this file exists to guard against). Logged in docs/scribble.md
    rather than fixed here, alongside this test's own scope note.
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
