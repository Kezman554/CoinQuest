"""Alembic environment.

The database URL comes from the environment, through app.config, and never
from alembic.ini: there is one database per deployment and a checked-in
default would eventually point a migration at the wrong one.

`render_as_batch` is on because the target is SQLite, which cannot ALTER a
column or drop a constraint. Batch mode rebuilds the table instead, which is
the only way a later revision will be able to change anything at all.

Rebuilding a table means dropping it, and SQLite refuses to drop a table
that another table's row still references with ON DELETE RESTRICT while
foreign key enforcement is on — which every real week does, the moment a
single chore has been claimed against it. app/db.py turns foreign_keys on
for every connection this process opens, migrations included, once it has
been imported — which it always has been by the time app.main's lifespan
calls this. So it is turned off here, on the raw connection, before
Alembic opens anything: SQLite only honours PRAGMA foreign_keys with no
transaction pending, and Alembic opens a real one around each migration
script for a dialect like this one that cannot run DDL transactionally
(MigrationContext.begin_transaction, called per-script) — an
`op.execute("PRAGMA foreign_keys=OFF")` inside a migration itself would run
inside that transaction and silently do nothing. Turned back on before the
connection is handed back, so the toggle never reaches anything the app
itself runs. Found the hard way: 2026-08-25, a real deploy against a real
household database with real chore_instances rows already in it — the
first time a table-rebuilding migration had ever run against loaded data
rather than an empty one.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which switches off every
    # logger already created — including coinquest.authorisation, whose whole
    # job is to leave a record of failed PIN attempts. Running a migration in
    # the same process would otherwise silence it.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # See the module docstring: must happen before anything else touches
        # this connection, and undone before it is handed back.
        raw = connection.connection.dbapi_connection
        raw.execute("PRAGMA foreign_keys=OFF")

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()

        raw.execute("PRAGMA foreign_keys=ON")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
