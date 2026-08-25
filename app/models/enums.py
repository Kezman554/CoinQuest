"""The fixed vocabularies of the scheme.

Stored as their string values, not as integers: a database that has to be read
by a person at half past ten on a Sunday should say "confirmed", not "2".
"""

from __future__ import annotations

import enum


class Cadence(str, enum.Enum):
    """How often a chore falls due."""

    DAILY = "daily"                        # one instance every day
    WEEKDAYS = "weekdays"                  # one instance on chosen days of the week
    WEEKLY_COUNT = "weekly_count"          # n instances somewhere in the week
    WEEKLY_CONDITION = "weekly_condition"  # one week-long condition, judged once
    ONE_OFF = "one_off"                    # a single instance on a given day
    EVENT = "event"                        # logged by a parent when it happens


#: Cadences that produce one instance for the whole week rather than per day.
WEEK_SCOPED_CADENCES = frozenset({Cadence.WEEKLY_COUNT, Cadence.WEEKLY_CONDITION})

#: Cadences a week's plan can predict from a definition alone. The other two
#: are created by a parent when they happen, so for those the instances that
#: exist are the requirement: somebody deliberately added each one. This is not
#: a hole in "assess the requirement, never the rows" — it is what the
#: requirement consists of when the scheme cannot know it in advance.
#:
#: WEEKDAYS belongs here on the same footing as DAILY: both are predictable
#: from the definition alone, WEEKDAYS just asks for fewer of the week's days.
WEEK_DERIVED_CADENCES = frozenset(
    {Cadence.DAILY, Cadence.WEEKDAYS, Cadence.WEEKLY_COUNT, Cadence.WEEKLY_CONDITION}
)

#: Cadences a child can decide to complete today, told this morning that
#: yesterday was missed. This is the property that makes a chore usable as a
#: recovery, and it is a fact about the cadence rather than about any
#: particular chore: no list of chore names appears anywhere in the recovery
#: rules, so adding a chore never means remembering to update them.
#:
#: A WEEKLY_CONDITION is excluded because it cannot be started on Thursday —
#: a condition held all week is either already true or already lost. An EVENT
#: is excluded because the child does not decide when it happens; somebody
#: else does, and a rule the child cannot act on is not a recovery route.
#:
#: WEEKDAYS belongs here too — on one of its own chosen days it is exactly as
#: on-demand as DAILY is every day. Membership in this set does not promise a
#: chore is doable on ANY day, only that when it is due, it is the child's to
#: decide: there is simply no instance to claim on a day it is not due, which
#: the ordinary "no instance, nothing to spend" check already handles.
ON_DEMAND_CADENCES = frozenset(
    {Cadence.DAILY, Cadence.WEEKDAYS, Cadence.WEEKLY_COUNT, Cadence.ONE_OFF}
)


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


class MissOrigin(str, enum.Enum):
    """How a miss came to be, which is two different facts.

    A parent marking a chore missed is a decision, definite the moment it is
    made, and it names who made it. A miss established at settlement is the
    absence of anything having happened: nobody decided it, so nobody is
    recorded as its author.
    """

    PARENT_MARKED = "parent_marked"
    INFERRED_AT_SETTLEMENT = "inferred_at_settlement"


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
    #: Undoing a deposit that should not have counted — a reopened week's
    #: payment, unwound. Not a WITHDRAWAL: the child did not choose to take
    #: this out, and calling it one would blur two facts a reader needs to
    #: tell apart a year later. The other fall, alongside WITHDRAWAL.
    REVERSAL = "reversal"
