"""What a parent needs to see before they decide anything.

Two things live here. The queue of claims waiting to be ruled on, and the
answer to the question a parent actually has in front of a list of ticks:
*what does agreeing to this do?*

The second is the point of the module. A batch described as "7 items" tells a
parent nothing they could not count themselves, and nothing at all about what
it does — whether the week still fails, whether a bonus chore is about to be
spent covering a miss, whether the total moves by 40p or by £2.40. The
consequence is computed by applying the batch for real inside a savepoint,
proposing the week from the result, and throwing the savepoint away. Applying
it is the only way to be sure the preview and the commit agree, because they
are then the same code over the same data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from sqlalchemy.orm import Session

from app.models.chores import ChoreDefinition, ChoreInstance
from app.models.enums import InstanceState, WeekStatus
from app.models.weeks import Week
from app.services import settlement
from app.services.authorisation import Authorisation
from app.services.review import Decision, apply_decisions


@dataclass(frozen=True)
class PendingClaim:
    """One claim waiting on a parent."""

    instance_id: int
    definition_id: int
    name: str
    category: str
    cadence: str
    amount_pence: int
    sequence: int
    due_date: date | None
    week_id: int
    week_start_date: date
    week_end_date: date
    claimed_at: str | None
    rejection_count: int


def pending(session: Session) -> list[PendingClaim]:
    """Every claim waiting to be ruled on, oldest first.

    Across weeks, because more than one may be open at a time and a claim on
    last week's Saturday is exactly the one most likely to be forgotten.
    """
    rows = (
        session.query(ChoreInstance, ChoreDefinition, Week)
        .join(ChoreDefinition, ChoreInstance.definition_id == ChoreDefinition.id)
        .join(Week, ChoreInstance.week_id == Week.id)
        .filter(ChoreInstance.state == InstanceState.CLAIMED)
        .filter(Week.status == WeekStatus.OPEN)
        .order_by(ChoreInstance.claimed_at, ChoreInstance.id)
        .all()
    )

    return [
        PendingClaim(
            instance_id=instance.id,
            definition_id=definition.id,
            name=definition.name,
            category=definition.category.value,
            cadence=definition.cadence.value,
            amount_pence=definition.amount_pence,
            sequence=instance.sequence,
            due_date=instance.due_date,
            week_id=week.id,
            week_start_date=week.start_date,
            week_end_date=week.end_date,
            claimed_at=instance.claimed_at.isoformat() if instance.claimed_at else None,
            rejection_count=instance.rejection_count,
        )
        for instance, definition, week in rows
    ]


@dataclass(frozen=True)
class Figures:
    """One week's position, before or after a batch."""

    misses: int
    misses_outstanding: int
    recoveries: tuple[tuple[str, str], ...]
    chore_pay_awarded: bool
    chore_pay_at_stake_pence: int
    chore_pay_pence: int
    bonus_pence: int
    reward_pence: int
    total_pence: int

    @classmethod
    def of(cls, proposal: settlement.Proposal) -> "Figures":
        return cls(
            misses=len(proposal.misses),
            misses_outstanding=proposal.misses_outstanding,
            recoveries=tuple(
                (recovery.miss_name, recovery.spent_name)
                for recovery in proposal.recoveries
            ),
            chore_pay_awarded=proposal.chore_pay_awarded,
            chore_pay_at_stake_pence=proposal.chore_pay_at_stake_pence,
            chore_pay_pence=proposal.chore_pay_pence,
            bonus_pence=proposal.bonus_pence,
            reward_pence=proposal.reward_pence,
            total_pence=proposal.total_pence,
        )


@dataclass(frozen=True)
class Consequence:
    """What this batch does to one week."""

    week_id: int
    start_date: date
    end_date: date
    before: Figures
    after: Figures
    confirmed: int
    rejected: int

    @property
    def difference_pence(self) -> int:
        return self.after.total_pence - self.before.total_pence

    @property
    def rescues_the_chore_pay(self) -> bool:
        return not self.before.chore_pay_awarded and self.after.chore_pay_awarded

    @property
    def loses_the_chore_pay(self) -> bool:
        return self.before.chore_pay_awarded and not self.after.chore_pay_awarded


#: The author recorded while previewing. Nothing written under it survives the
#: savepoint, and it is not the string a real confirmation is stored with — a
#: preview that wrote "parent" into a column, even briefly, would be one bug
#: away from being indistinguishable from the real thing in the record.
PREVIEW = "preview"


def preview(
    session: Session,
    decisions: list[Decision],
    tz: tzinfo,
    *,
    at: datetime,
) -> tuple[Consequence, ...]:
    """What this batch would do, per week. Changes nothing.

    The batch is applied inside a savepoint and the savepoint is rolled back,
    so the figures come from the real code path over the real data rather than
    from a second implementation that agrees with it today.

    Raises ReviewError if the batch could not be applied at all, which is the
    same refusal the commit would give and is worth knowing before typing a
    PIN rather than after.
    """
    instances = [session.get(ChoreInstance, d.instance_id) for d in decisions]
    week_ids = {instance.week_id for instance in instances if instance is not None}
    weeks = [session.get(Week, week_id) for week_id in sorted(week_ids)]
    weeks = [week for week in weeks if week is not None]

    before = {
        week.id: Figures.of(settlement.propose(session, week, tz))
        for week in weeks
        if week.status is WeekStatus.OPEN
    }

    after: dict[int, Figures] = {}
    savepoint = session.begin_nested()
    try:
        apply_decisions(session, decisions, Authorisation(party=PREVIEW, at=at))
        after = {
            week.id: Figures.of(settlement.propose(session, week, tz))
            for week in weeks
            if week.status is WeekStatus.OPEN
        }
    finally:
        # Always. A preview that leaves anything behind on the way out of an
        # error is worse than no preview at all.
        savepoint.rollback()
        session.expire_all()

    by_week: dict[int, list[int]] = {}
    for instance, decision in zip(instances, decisions):
        if instance is not None:
            by_week.setdefault(instance.week_id, []).append(
                1 if decision.decision == "confirm" else 0
            )

    return tuple(
        Consequence(
            week_id=week.id,
            start_date=week.start_date,
            end_date=week.end_date,
            before=before[week.id],
            after=after[week.id],
            confirmed=sum(by_week.get(week.id, [])),
            rejected=len(by_week.get(week.id, [])) - sum(by_week.get(week.id, [])),
        )
        for week in weeks
        if week.id in before and week.id in after
    )
