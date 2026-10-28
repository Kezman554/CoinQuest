"""Every migration, one at a time, against a database already full of rows.

Session AO. `test_migration_against_real_data.py` seeds once, straight after
the initial migration, and then runs the whole chain. That catches a rebuild
tripping over a foreign key, but only for rows of the kinds that existed at
the very start — and it deliberately seeded no confirmed or missed instance,
because two migrations could not have migrated one:

  - e42da40283c5 added `authorised_by` and a CHECK that a confirmation names
    its author, with no backfill, so an instance already confirmed failed the
    CHECK the moment the table was rebuilt.
  - 82826e03b64d added `miss_origin` and a CHECK that a miss says how it
    arose, with the same shape for an instance already missed.

Both had already run on the live database by the time anyone noticed, because
that database was born after them (2026-08-21; both were committed the day
before). Every test then built its database from empty, so that shape could
pass forever. Both now backfill, and this file is what keeps the next one
honest.

For each migration in turn: migrate a scratch database to the revision just
before it, seed realistic rows into every table that exists at that point —
the rows the application at that revision could actually have written,
confirmed and missed instances and claims included — then upgrade through
that one migration and require that it succeeds and that every row survives.

The seed is written once and reshapes itself to the schema it finds: a value
for a column that does not exist yet is left out, and a row that cannot exist
without some later column or table (a second weekly-count instance before
`sequence`, a standalone deposit before `posted_by`) is left out until it can.
What it never does is leave out a value a column *does* require: a confirmed
instance at a revision with `authorised_by` names its parent, because the app
always did. A new table nobody taught the seed about fails the test on the
spot rather than going unseeded.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

T = "2026-08-{:02d} {}:00.000000"  # a UtcDateTime as stored: naive UTC text


def _at(day: int, hhmm: str = "18:00") -> str:
    return T.format(day, hhmm)


#: (table, values, needs). A value whose column does not exist at the seeded
#: revision is dropped; a row whose `needs` are not all present — each a
#: column of its own table, or "table:<name>" — is skipped entirely.
#:
#: Weeks run Sunday to Saturday: 2 Aug settled, paid and overridden; 9 Aug
#: voided; 16 Aug open, having been settled once and reopened.
SEED: list[tuple[str, dict, tuple[str, ...]]] = [
    # --- chore definitions -------------------------------------------------
    ("chore_definitions", {
        "id": 1, "name": "Make bed", "cadence": "daily", "category": "basic",
        "amount_pence": 0, "is_available": 1,
        "created_at": _at(1), "updated_at": _at(1),
    }, ()),
    ("chore_definitions", {
        "id": 2, "name": "Practise piano", "cadence": "weekly_count",
        "category": "bonus", "amount_pence": 50, "times_per_week": 3,
        "is_available": 1, "created_at": _at(1), "updated_at": _at(1),
    }, ()),
    ("chore_definitions", {
        "id": 3, "name": "Take the bins out", "cadence": "weekdays",
        "category": "basic", "amount_pence": 0, "weekdays": "tuesday,friday",
        "is_available": 1, "created_at": _at(1), "updated_at": _at(1),
    }, ("weekdays",)),
    ("chore_definitions", {
        "id": 4, "name": "Take medicine", "cadence": "daily",
        "category": "basic", "amount_pence": 0, "is_administered": 1,
        "is_available": 1, "created_at": _at(1), "updated_at": _at(1),
    }, ("is_administered",)),
    # A retired chore: still referenced by history, no longer offered.
    ("chore_definitions", {
        "id": 5, "name": "Feed the fish", "cadence": "one_off",
        "category": "reward", "amount_pence": 100, "is_available": 0,
        "created_at": _at(1), "updated_at": _at(1),
    }, ()),
    # --- weeks -------------------------------------------------------------
    ("weeks", {
        "id": 1, "start_date": "2026-08-02", "end_date": "2026-08-08",
        "status": "settled",
        # One name before 4e720209aaba, the other after; only one exists.
        "settled_basic_pence": 250, "settled_chore_pay_pence": 250,
        "settled_base_pence": 0,
        "settled_bonus_pence": 50, "settled_reward_pence": 0,
        "settled_total_pence": 300, "closed_at": _at(8, "19:00"),
        "overridden_by": "parent", "optimum_total_pence": 400,
        "override_reason": "Beds made only after being asked twice",
        "paid_at": _at(9, "09:00"), "deposited_pence": 300,
        "created_at": _at(2),
    }, ()),
    ("weeks", {
        "id": 2, "start_date": "2026-08-09", "end_date": "2026-08-15",
        "status": "voided",
        "settled_basic_pence": 0, "settled_chore_pay_pence": 0,
        "settled_base_pence": 0,
        "settled_bonus_pence": 0, "settled_reward_pence": 0,
        "settled_total_pence": 0, "closed_at": _at(15, "19:00"),
        "void_reason": "Away on holiday", "created_at": _at(9),
    }, ()),
    ("weeks", {
        "id": 3, "start_date": "2026-08-16", "end_date": "2026-08-22",
        "status": "open", "created_at": _at(16),
    }, ()),
    # --- chore instances ---------------------------------------------------
    # Week 1, settled: five confirmed, one miss a parent marked, one miss
    # inferred at settlement. Each says what the app at its revision said.
    *[
        ("chore_instances", {
            "definition_id": 1, "week_id": 1, "due_date": f"2026-08-{d:02d}",
            "state": "confirmed", "quantity": 1,
            "claimed_at": _at(d, "07:30"), "confirmed_at": _at(d, "20:00"),
            "authorised_by": "parent", "created_at": _at(2),
        }, ())
        for d in range(2, 7)
    ],
    ("chore_instances", {
        "definition_id": 1, "week_id": 1, "due_date": "2026-08-07",
        "state": "missed", "quantity": 1, "missed_at": _at(7, "20:00"),
        "miss_origin": "parent_marked", "authorised_by": "parent",
        "created_at": _at(2),
    }, ()),
    ("chore_instances", {
        "definition_id": 1, "week_id": 1, "due_date": "2026-08-08",
        "state": "missed", "quantity": 1, "missed_at": _at(8, "19:00"),
        "miss_origin": "inferred_at_settlement", "created_at": _at(2),
    }, ()),
    ("chore_instances", {
        "definition_id": 2, "week_id": 1, "due_date": None, "sequence": 1,
        "state": "confirmed", "quantity": 1,
        "claimed_at": _at(4, "17:00"), "confirmed_at": _at(4, "20:00"),
        "authorised_by": "parent", "created_at": _at(2),
    }, ()),
    ("chore_instances", {
        "definition_id": 2, "week_id": 1, "due_date": None, "sequence": 2,
        "state": "confirmed", "quantity": 1,
        "claimed_at": _at(6, "17:00"), "confirmed_at": _at(6, "20:00"),
        "authorised_by": "parent", "created_at": _at(2),
    }, ("sequence",)),
    # Week 2, voided: nothing happened.
    ("chore_instances", {
        "definition_id": 1, "week_id": 2, "due_date": "2026-08-09",
        "state": "untouched", "quantity": 1, "created_at": _at(9),
    }, ()),
    # Week 3, open: claims waiting for a parent, one claim already rejected
    # and given back, and the days still to come.
    *[
        ("chore_instances", {
            "definition_id": 1, "week_id": 3, "due_date": f"2026-08-{d:02d}",
            "state": "claimed", "quantity": 1, "claimed_at": _at(d, "07:30"),
            "created_at": _at(16),
        }, ())
        for d in (16, 17)
    ],
    ("chore_instances", {
        "definition_id": 1, "week_id": 3, "due_date": "2026-08-18",
        "state": "untouched", "quantity": 1,
        "rejection_count": 1, "rejected_at": _at(18, "20:00"),
        "created_at": _at(16),
    }, ("rejection_count",)),
    ("chore_instances", {
        "definition_id": 1, "week_id": 3, "due_date": "2026-08-19",
        "state": "untouched", "quantity": 1, "created_at": _at(16),
    }, ()),
    ("chore_instances", {
        "definition_id": 3, "week_id": 3, "due_date": "2026-08-18",
        "state": "claimed", "quantity": 1, "claimed_at": _at(18, "19:00"),
        "created_at": _at(16),
    }, ("table:chore_definitions.weekdays",)),
    ("chore_instances", {
        "definition_id": 2, "week_id": 3, "due_date": None, "sequence": 1,
        "state": "claimed", "quantity": 1, "claimed_at": _at(17, "17:00"),
        "created_at": _at(16),
    }, ()),
    # --- settlement lines --------------------------------------------------
    ("settlement_lines", {
        "id": 1, "week_id": 1, "chore_name": "Make bed", "category": "basic",
        "cadence": "daily", "unit_amount_pence": 50, "quantity": 5,
        "amount_pence": 250, "source_definition_id": 1,
        "created_at": _at(8, "19:00"),
    }, ()),
    ("settlement_lines", {
        "id": 2, "week_id": 1, "chore_name": "Practise piano",
        "category": "bonus", "cadence": "weekly_count",
        "unit_amount_pence": 25, "quantity": 2, "amount_pence": 50,
        "source_definition_id": 2, "note": "Two of three",
        "created_at": _at(8, "19:00"),
    }, ()),
    # --- waivers -----------------------------------------------------------
    ("waivers", {
        "id": 1, "scope": "day", "day": "2026-08-20",
        "reason": "Dentist", "created_at": _at(16),
    }, ()),
    ("waivers", {
        "id": 2, "scope": "chore_week", "week_id": 3, "definition_id": 2,
        "reason": "Piano teacher away", "created_at": _at(16),
    }, ()),
    # --- earnings ----------------------------------------------------------
    ("earnings_ledger", {
        "id": 1, "entry_type": "week_settlement", "amount_pence": 300,
        "week_id": 1, "occurred_on": "2026-08-08", "created_at": _at(8, "19:00"),
    }, ()),
    ("earnings_ledger", {
        "id": 2, "entry_type": "week_settlement", "amount_pence": 0,
        "week_id": 2, "occurred_on": "2026-08-15", "created_at": _at(15, "19:00"),
    }, ()),
    ("earnings_ledger", {
        "id": 3, "entry_type": "reward", "amount_pence": 100,
        "occurred_on": "2026-08-12", "reason": "Fed the fish all week",
        "created_at": _at(12),
    }, ()),
    # --- savings -----------------------------------------------------------
    ("savings_ledger", {
        "id": 1, "entry_type": "opening_balance", "amount_pence": 100,
        "balance_after_pence": 100, "occurred_on": "2026-08-01",
        "created_at": _at(1),
    }, ()),
    ("savings_ledger", {
        "id": 2, "entry_type": "deposit", "amount_pence": 300,
        "balance_after_pence": 400, "week_id": 1, "occurred_on": "2026-08-09",
        "created_at": _at(9, "09:00"),
    }, ()),
    ("savings_ledger", {
        "id": 3, "entry_type": "withdrawal", "amount_pence": -50,
        "balance_after_pence": 350, "occurred_on": "2026-08-14",
        "reason": "Comic", "created_at": _at(14),
    }, ()),
    ("savings_ledger", {
        "id": 4, "entry_type": "match", "amount_pence": 5,
        "balance_after_pence": 355, "occurred_on": "2026-08-31",
        "reason": "Interest for August", "created_at": _at(31),
    }, ()),
    ("savings_ledger", {
        "id": 5, "entry_type": "deposit", "amount_pence": 200,
        "balance_after_pence": 555, "occurred_on": "2026-08-20",
        "reason": "Birthday money", "posted_by": "parent",
        "created_at": _at(20),
    }, ("posted_by",)),
    # --- scheme settings: its one row is inserted by its own migration -----
    # --- reopenings, matches, deposit requests: later tables ---------------
    ("week_reopenings", {
        "id": 1, "week_id": 3, "reopened_by": "parent",
        "reopened_at": _at(22, "20:00"), "reason": "Forgot Tuesday's bins",
        "previous_status": "settled", "previous_base_pence": 0,
        "previous_chore_pay_pence": 200, "previous_bonus_pence": 0,
        "previous_reward_pence": 0, "previous_total_pence": 200,
        "previous_closed_at": _at(22, "19:00"), "was_paid": 0,
        "reversed_deposit_pence": 0,
    }, ()),
    ("savings_month_matches", {
        "id": 1, "period_start": "2026-08-01", "period_end": "2026-08-31",
        "balance_low_pence": 100, "had_withdrawal": 1, "rate_percent": 5,
        "cap_pence": 10000, "match_pence": 5, "match_entry_id": 4,
        "settled_by": "parent", "settled_at": _at(31), "created_at": _at(31),
    }, ()),
    ("savings_deposit_requests", {
        "id": 1, "amount_pence": 200, "note": "Birthday money",
        "posted_by": "Test Child", "occurred_on": "2026-08-20",
        "state": "confirmed", "submitted_at": _at(20, "10:00"),
        "decided_at": _at(20), "decided_by": "parent", "savings_entry_id": 5,
    }, ()),
    ("savings_deposit_requests", {
        "id": 2, "amount_pence": 500, "note": "Found it",
        "posted_by": "Test Child", "occurred_on": "2026-08-21",
        "state": "rejected", "submitted_at": _at(21, "10:00"),
        "decided_at": _at(21), "decided_by": "parent",
    }, ()),
    ("savings_deposit_requests", {
        "id": 3, "amount_pence": 150, "note": "Tooth fairy",
        "posted_by": "Test Child", "occurred_on": "2026-08-22",
        "state": "pending", "submitted_at": _at(22, "08:00"),
    }, ()),
]

#: Tables that arrive already holding their rows, put there by the migration
#: that created them, which the seed must not add to.
SEEDED_BY_THEIR_MIGRATION = {"scheme_settings"}


def _columns(con, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def _tables(con) -> set[str]:
    return {
        name
        for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' AND name <> 'alembic_version'"
        )
    }


def _seed(db_path: Path) -> dict[str, int]:
    """Insert every SEED row the schema at this revision can hold, with
    foreign keys enforced as in production, and return the count per table.
    """
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=ON")
        tables = _tables(con)
        columns = {table: _columns(con, table) for table in tables}

        def present(need: str, table: str) -> bool:
            if need.startswith("table:"):
                other, _, column = need[len("table:"):].partition(".")
                return other in tables and (not column or column in columns[other])
            return need in columns[table]

        for table, values, needs in SEED:
            if table not in tables:
                continue
            if not all(present(need, table) for need in needs):
                continue
            row = {k: v for k, v in values.items() if k in columns[table]}
            names = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            con.execute(
                f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values())
            )
        con.commit()

        counts = {
            table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in tables
        }
    finally:
        con.close()

    unseeded = {
        table for table, n in counts.items()
        if n == 0 and table not in SEEDED_BY_THEIR_MIGRATION
    }
    assert not unseeded, (
        f"no seed rows for {sorted(unseeded)}: add them to SEED, or this "
        "test proves nothing about migrating them"
    )
    return counts


def _states(db_path: Path) -> dict[str, int]:
    con = sqlite3.connect(str(db_path))
    try:
        return dict(
            con.execute(
                "SELECT state, count(*) FROM chore_instances GROUP BY state"
            ).fetchall()
        )
    finally:
        con.close()


def _chain() -> list[str]:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config("sqlite://"))
    return [rev.revision for rev in reversed(list(script.walk_revisions()))]


def _config(database_url: str):
    from alembic.config import Config

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


CHAIN = _chain()


@pytest.mark.parametrize(
    "before, revision",
    list(zip(CHAIN, CHAIN[1:])),
    ids=CHAIN[1:],
)
def test_the_migration_upgrades_a_database_already_holding_rows(
    before, revision, tmp_path, monkeypatch
):
    from alembic import command

    # Imported for its side effect: the connect listener that turns foreign
    # keys on, which a real deploy always has in place (see the module
    # docstring of test_migration_against_real_data.py).
    import app.db  # noqa: F401

    db_path = tmp_path / "seeded.db"
    url = f"sqlite:///{db_path.as_posix()}"
    # env.py reads the URL from settings, not from the Config; this has to be
    # in place before the first alembic call.
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()
    config = _config(url)
    try:
        command.upgrade(config, before)
        seeded = _seed(db_path)
        states_before = _states(db_path)
        command.upgrade(config, revision)
    finally:
        get_settings.cache_clear()

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA foreign_keys=ON")
        (version,) = con.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == revision
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []

        for table, expected in seeded.items():
            (count,) = con.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert count == expected, f"{table}: seeded {expected}, found {count}"

    finally:
        con.close()

    # Counts alone would pass a migration that kept every row but reset its
    # state; a confirmation or a miss quietly becoming something else is
    # exactly what a careless backfill would do.
    assert _states(db_path) == states_before
    assert {"untouched", "claimed", "confirmed", "missed"} <= set(states_before)
