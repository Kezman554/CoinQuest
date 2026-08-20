"""The fixed vocabularies of the scheme.

Stored as their string values, not as integers: a database that has to be read
by a person at half past ten on a Sunday should say "confirmed", not "2".
"""

from __future__ import annotations

import enum


class Cadence(str, enum.Enum):
    """How often a chore falls due."""

    DAILY = "daily"                        # one instance every day
    WEEKLY_COUNT = "weekly_count"          # n instances somewhere in the week
    WEEKLY_CONDITION = "weekly_condition"  # one week-long condition, judged once
    ONE_OFF = "one_off"                    # a single instance on a given day
    EVENT = "event"                        # logged by a parent when it happens


#: Cadences that produce one instance for the whole week rather than per day.
WEEK_SCOPED_CADENCES = frozenset({Cadence.WEEKLY_COUNT, Cadence.WEEKLY_CONDITION})


class Category(str, enum.Enum):
    """What a chore does to the money, which is what makes it a category."""

    BASIC = "basic"    # counts toward the weekly chore pay, and can be missed
    BONUS = "bonus"    # a fixed amount, all or nothing, once per week
    REWARD = "reward"  # pays its own amount when it happens


class InstanceState(str, enum.Enum):
    """Where one instance of a chore has got to.

    UNTOUCHED is provisional: nobody has said anything about it yet. It only
    becomes a miss at settlement, which is what makes the recovery window
    usable rather than punitive.
    """

    UNTOUCHED = "untouched"
    CLAIMED = "claimed"      # the child says it is done; not yet money
    CONFIRMED = "confirmed"  # a parent has agreed it
    MISSED = "missed"        # a parent marked it missed, or settlement did


class WeekStatus(str, enum.Enum):
    """OPEN weeks are computed. SETTLED and VOIDED weeks are read."""

    OPEN = "open"
    SETTLED = "settled"
    VOIDED = "voided"


class WaiverScope(str, enum.Enum):
    """What a waiver excuses."""

    DAY = "day"                # a whole day, for everything
    CHORE_WEEK = "chore_week"  # one chore, for one week


class EarningType(str, enum.Enum):
    """Why money entered the earnings ledger."""

    WEEK_SETTLEMENT = "week_settlement"  # the closing figure for one week
    REWARD = "reward"                    # an ad-hoc reward, with a reason


class SavingsType(str, enum.Enum):
    """Why the savings balance moved."""

    OPENING_BALANCE = "opening_balance"  # what was already there on day one
    DEPOSIT = "deposit"                  # part of a payday, kept back
    WITHDRAWAL = "withdrawal"            # money taken out; the only fall
    MATCH = "match"                      # the monthly match, once settled
