"""Alembic environment.

The database URL comes from the environment, through app.config, and never
from alembic.ini: there is one database per deployment and a checked-in
default would eventually point a migration at the wrong one.

`render_as_batch` is on because the target is SQLite, which cannot ALTER a
column or drop a constraint. Batch mode rebuilds the table instead, which is
the only way a later revision will be able to change anything at all.
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
