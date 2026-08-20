"""Declarative base and the column types every table shares."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase

# Naming every constraint means Alembic can alter one later. SQLite cannot
# drop an unnamed constraint at all, so this has to be in place from the very
# first revision.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator):
    """An instant, stored as UTC and returned aware.

    SQLite has no datetime type and keeps whatever string it is handed, so an
    aware datetime would silently lose its offset on the way in and come back
    naive. Everything recorded here is an instant in UTC; the local day it
    belongs to is a separate, explicit column, computed in Europe/London by
    app.services.calendar.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; supply the zone.")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_class: type) -> Enum:
    """A VARCHAR holding the enum's value, with a CHECK listing the options.

    native_enum=False keeps the readable string rather than an ordinal, and
    the CHECK means a typo in a hand-written INSERT is refused by the database
    rather than read back later as a state nothing knows how to handle.
    """
    return Enum(
        enum_class,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        name=f"ck_{enum_class.__name__.lower()}",
    )


def utcnow() -> datetime:
    """The current instant. Local days never come from this — see calendar."""
    return datetime.now(timezone.utc)
