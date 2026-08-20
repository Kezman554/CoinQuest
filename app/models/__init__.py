"""The database schema.

Importing this package imports every model, which is what Alembic's autogenerate
and Base.metadata.create_all both rely on.
"""

from __future__ import annotations

from app.models.base import Base, UtcDateTime, utcnow
from app.models.chores import ChoreDefinition, ChoreInstance
from app.models.enums import (
    WEEK_SCOPED_CADENCES,
    Cadence,
    Category,
    EarningType,
    InstanceState,
    SavingsType,
    WaiverScope,
    WeekStatus,
)
from app.models.ledgers import EarningEntry, SavingsEntry
from app.models.waivers import Waiver
from app.models.weeks import SettlementLine, Week

__all__ = [
    "WEEK_SCOPED_CADENCES",
    "Base",
    "Cadence",
    "Category",
    "ChoreDefinition",
    "ChoreInstance",
    "EarningEntry",
    "EarningType",
    "InstanceState",
    "SavingsEntry",
    "SavingsType",
    "SettlementLine",
    "UtcDateTime",
    "Waiver",
    "WaiverScope",
    "Week",
    "WeekStatus",
    "utcnow",
]
