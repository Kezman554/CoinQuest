"""The database schema.

Importing this package imports every model, which is what Alembic's autogenerate
and Base.metadata.create_all both rely on.
"""

from __future__ import annotations

from app.models.base import Base, UtcDateTime, utcnow
from app.models.chores import ChoreDefinition, ChoreInstance
from app.models.enums import (
    ON_DEMAND_CADENCES,
    WEEK_DERIVED_CADENCES,
    WEEK_SCOPED_CADENCES,
    Cadence,
    Category,
    EarningType,
    InstanceState,
    MissOrigin,
    SavingsType,
    WaiverScope,
    WeekStatus,
)
from app.models.ledgers import EarningEntry, SavingsEntry
from app.models.savings_match import SavingsMonthMatch
from app.models.settings import SchemeSettings
from app.models.waivers import Waiver
from app.models.weeks import SettlementLine, Week, WeekReopening

__all__ = [
    "ON_DEMAND_CADENCES",
    "WEEK_DERIVED_CADENCES",
    "WEEK_SCOPED_CADENCES",
    "Base",
    "Cadence",
    "Category",
    "ChoreDefinition",
    "ChoreInstance",
    "EarningEntry",
    "EarningType",
    "InstanceState",
    "MissOrigin",
    "SavingsEntry",
    "SavingsMonthMatch",
    "SavingsType",
    "SchemeSettings",
    "SettlementLine",
    "UtcDateTime",
    "Waiver",
    "WaiverScope",
    "Week",
    "WeekReopening",
    "WeekStatus",
    "utcnow",
]
