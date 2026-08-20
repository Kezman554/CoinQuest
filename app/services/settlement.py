"""Proposing a week's figures, and closing it on them.

Two operations, and the whole design is in the gap between them.

`propose` works out what the week is worth and writes nothing at all. It can be
called every five minutes by a dashboard tile, on a Wednesday, on any open
week, and it changes nothing. `settle` takes a proposal a parent has actually
read and agreed, writes the amounts into the week, and closes it.

After that the week is a closed event. Its figures are stored, not derived, and
nothing recomputes them — `propose` refuses a week that is not open, which is
the mechanism rather than the intention: there is no path from a settled week
back to a current definition, so editing a chore tomorrow cannot reach
backwards into what was paid last month. Each settlement line keeps its own
copy of the chore's name and amount as they read that week, so the record
survives the definition being renamed, repriced or deleted outright.

More than one week may be open at once, and each settles independently on its
own figures. Nothing here reads "the current week".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.chores import ChoreDefinition, ChoreInstance
from app.models.enums import (
    Cadence,
    Category,
    EarningType,
    InstanceState,
    WeekStatus,
)
from app.models.ledgers import EarningEntry
from app.models.waivers import Waiver
from app.models.weeks import SettlementLine, Week
from app.services.authorisation import Authorisation
from app.services.calendar import Period
from app.services.instances import plan_week
from app.services.recovery import (
    RECOVERY_CAP,
    Assignment,
    Miss,
    Requirement,
    WeekAssessment,
    assess_week,
    best_assignment,
    record_inferred_misses,
)


class NotOpen(Exception):
    """The week is settled or voided. Closed is closed."""


class ProposalChanged(Exception):
    """The week is no longer worth what the parent agreed to.

    Raised when the figure submitted with the agreement does not match the
    figure the week currently proposes — because a claim was confirmed, or a
    waiver added, between the parent reading the proposal and agreeing it.
    Settling anyway would store an amount nobody actually agreed.
    """


@dataclass(frozen=True)
class Recovery:
    """One miss covered by one bonus chore, worked and forgone."""

    miss_definition_id: int
    miss_name: str
    spent_definition_id: int
    spent_name: str
    forgone_pence: int


@dataclass(frozen=True)
class ProposedLine:
    """One line of the week's figures, ready to be frozen into the record."""

    definition_id: int
    chore_name: str
    category: Category
    cadence: Cadence
    unit_amount_pence: int
    quantity: int
    amount_pence: int
    note: str | None = None


@dataclass(frozen=True)
class Proposal:
    """What a week is worth, computed and applied to nothing.

    `base_pence` is the chore pay the week put at stake — everything the basic
    chores were worth. `chore_pay_pence` is what it actually comes to: the
    whole of the base, or nothing at all. It is not apportioned. A week whose
    misses cannot be recovered pays no chore pay, which is the rule the
    recovery route exists to soften.
    """

    week_id: int
    start_date: date
    end_date: date
    base_pence: int
    chore_pay_pence: int
    bonus_pence: int
    reward_pence: int
    total_pence: int
    misses: tuple[Miss, ...]
    recoveries: tuple[Recovery, ...]
    requirements: tuple[Requirement, ...]
    lines: tuple[ProposedLine, ...]
    days_waived: int
    cap: int

    @property
    def chore_pay_awarded(self) -> bool:
        return self.chore_pay_pence > 0 or self.base_pence == 0

    @property
    def misses_outstanding(self) -> int:
        return len(self.misses) - len(self.recoveries)


def week_period(week: Week, tz) -> Period:
    return Period(start=week.start_date, end=week.end_date, tz=tz)


def propose(session: Session, week: Week, tz, *, cap: int = RECOVERY_CAP) -> Proposal:
    """Work out what an open week is worth. Writes nothing.

    Refuses a closed week. That refusal is the whole guarantee: a settled
    week's figures are read from its own columns and there is no code path
    that would rebuild them from today's definitions.
    """
    if week.status is not WeekStatus.OPEN:
        raise NotOpen(
            f"Week {week.start_date.isoformat()} is {week.status.value}."
            " A closed week is read, never recomputed."
        )

    definitions = session.query(ChoreDefinition).all()
    waivers = session.query(Waiver).all()
    instances = session.query(ChoreInstance).filter(ChoreInstance.week_id == week.id).all()

    plan = plan_week(week_period(week, tz), definitions, waivers, week_id=week.id)
    assessment = assess_week(plan, definitions, instances, cap=cap)
    assignment = best_assignment(assessment)

    recoveries = _recoveries(assessment, assignment)
    lines = _lines(assessment, assignment)

    return Proposal(
        week_id=week.id,
        start_date=week.start_date,
        end_date=week.end_date,
        base_pence=assessment.basic_pay_pence,
        chore_pay_pence=assignment.chore_pay_pence,
        bonus_pence=assignment.bonus_pay_pence,
        reward_pence=assignment.reward_pence,
        total_pence=assignment.total_pence,
        misses=assessment.misses,
        recoveries=recoveries,
        requirements=assessment.requirements,
        lines=lines,
        days_waived=plan.days_waived,
        cap=cap,
    )


def _recoveries(assessment: WeekAssessment, assignment: Assignment) -> tuple[Recovery, ...]:
    """Pair each spent bonus chore with the miss it covers.

    The pairing is presentational — the optimiser chose a set, and any miss is
    as good as any other to point it at — but a parent reading the proposal
    wants to see which chore paid for which, not a bare count.
    """
    spent = [
        assessment.requirement(definition_id)
        for definition_id in assignment.spent_definition_ids
    ]
    return tuple(
        Recovery(
            miss_definition_id=miss.definition_id,
            miss_name=miss.name,
            spent_definition_id=requirement.definition_id,
            spent_name=requirement.name,
            forgone_pence=requirement.amount_pence,
        )
        for miss, requirement in zip(assessment.misses, spent)
    )


def _lines(assessment: WeekAssessment, assignment: Assignment) -> tuple[ProposedLine, ...]:
    """Every chore the week assessed, and what it came to.

    Zero-value lines are kept. A basic chore that was missed, and a bonus
    chore worked and spent on a recovery, both happened, and a record that
    only lists what paid is not a record of the week.
    """
    lines: list[ProposedLine] = []

    for requirement in assessment.requirements:
        if not requirement.is_assessed:
            continue

        if requirement.category is Category.BASIC:
            paid = requirement.amount_pence if assignment.chore_pay_pence else 0
            note = None if paid else "no chore pay this week"
            if not requirement.met:
                note = "missed" if not paid else "missed, recovered"
            lines.append(_line(requirement, quantity=1, amount=paid, note=note))

        elif requirement.category is Category.BONUS:
            if not requirement.met:
                lines.append(
                    _line(requirement, quantity=1, amount=0, note="not completed")
                )
            elif requirement.definition_id in assignment.spent_definition_ids:
                lines.append(
                    _line(
                        requirement,
                        quantity=1,
                        amount=0,
                        note="worked unpaid, to recover a miss",
                    )
                )
            else:
                lines.append(
                    _line(requirement, quantity=1, amount=requirement.amount_pence)
                )

        elif requirement.category is Category.REWARD and requirement.confirmed:
            lines.append(
                _line(
                    requirement,
                    quantity=requirement.confirmed,
                    amount=requirement.amount_pence * requirement.confirmed,
                )
            )

    return tuple(lines)


def _line(requirement: Requirement, *, quantity: int, amount: int, note=None) -> ProposedLine:
    return ProposedLine(
        definition_id=requirement.definition_id,
        chore_name=requirement.name,
        category=requirement.category,
        cadence=requirement.cadence,
        unit_amount_pence=requirement.amount_pence,
        quantity=quantity,
        amount_pence=amount,
        note=note,
    )


def settle(
    session: Session,
    week: Week,
    proposal: Proposal,
    authorisation: Authorisation,
    *,
    agreed_total_pence: int,
) -> Week:
    """Close a week on figures a parent has read and agreed.

    The agreed total is checked against the proposal rather than trusted. If
    anything moved between the parent reading the figures and agreeing them,
    this refuses, because storing forever an amount nobody agreed to is the
    one mistake that cannot be corrected later.
    """
    if week.status is not WeekStatus.OPEN:
        raise NotOpen(f"Week {week.start_date.isoformat()} is already closed.")

    if agreed_total_pence != proposal.total_pence:
        raise ProposalChanged(
            f"This week now proposes {proposal.total_pence}p, not"
            f" {agreed_total_pence}p. Read the figures again before agreeing."
        )

    # The misses become real here and not before. Until this moment an
    # untouched instance was provisional, which is what gave the child the
    # rest of the week to do something about it.
    record_inferred_misses(session, proposal.misses)
    _link_recoveries(session, week, proposal)

    for line in proposal.lines:
        session.add(
            SettlementLine(
                week_id=week.id,
                chore_name=line.chore_name,      # a copy, taken now
                category=line.category,
                cadence=line.cadence,
                unit_amount_pence=line.unit_amount_pence,
                quantity=line.quantity,
                amount_pence=line.amount_pence,
                source_definition_id=line.definition_id,  # provenance only
                note=line.note,
            )
        )

    week.status = WeekStatus.SETTLED
    week.settled_basic_pence = proposal.chore_pay_pence
    week.settled_bonus_pence = proposal.bonus_pence
    week.settled_reward_pence = proposal.reward_pence
    week.settled_total_pence = proposal.total_pence
    week.closed_at = authorisation.at

    session.add(
        EarningEntry(
            entry_type=EarningType.WEEK_SETTLEMENT,
            amount_pence=proposal.total_pence,
            week_id=week.id,
            occurred_on=week.end_date,
            reason=f"Week {week.start_date.isoformat()} settled",
        )
    )

    session.flush()
    return week


def _link_recoveries(session: Session, week: Week, proposal: Proposal) -> None:
    """Record which confirmed bonus instance was spent on which miss.

    Best effort and deliberately so: the money is already decided by the
    figures above, and this only makes the stored week easier to read back.
    """
    missed_by_definition: dict[int, list[int]] = {}
    for miss in proposal.misses:
        if miss.instance_id is not None:
            missed_by_definition.setdefault(miss.definition_id, []).append(
                miss.instance_id
            )

    for recovery in proposal.recoveries:
        target = missed_by_definition.get(recovery.miss_definition_id)
        if not target:
            continue
        spent = (
            session.query(ChoreInstance)
            .filter(
                ChoreInstance.week_id == week.id,
                ChoreInstance.definition_id == recovery.spent_definition_id,
                ChoreInstance.state == InstanceState.CONFIRMED,
                ChoreInstance.recovered_instance_id.is_(None),
            )
            .first()
        )
        if spent is not None:
            spent.recovered_instance_id = target.pop(0)


def void(
    session: Session,
    week: Week,
    authorisation: Authorisation,
    *,
    reason: str,
) -> Week:
    """Close a week paying nothing, without erasing what was done.

    Every instance stays exactly as it is: the claims, the confirmations and
    the misses are the record of the week, and voiding is a statement about
    the money rather than about the work.

    Rewards already earned are not touched. They were earned by something
    happening, not by the week going well, so they are written to the earnings
    ledger in their own right — the week's own figures are all zero, and the
    reward survives the week paying nothing.
    """
    if week.status is not WeekStatus.OPEN:
        raise NotOpen(f"Week {week.start_date.isoformat()} is already closed.")

    if not reason or not reason.strip():
        raise ValueError("Voiding a week is unusual enough to want a reason.")

    for entry in _rewards_earned(session, week):
        session.add(entry)

    week.status = WeekStatus.VOIDED
    week.settled_basic_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = 0
    week.settled_total_pence = 0
    week.closed_at = authorisation.at
    week.void_reason = reason.strip()

    session.flush()
    return week


def _rewards_earned(session: Session, week: Week) -> list[EarningEntry]:
    """Rewards confirmed during a week, as ledger entries in their own right."""
    rows = (
        session.query(ChoreInstance, ChoreDefinition)
        .join(ChoreDefinition, ChoreInstance.definition_id == ChoreDefinition.id)
        .filter(
            ChoreInstance.week_id == week.id,
            ChoreInstance.state == InstanceState.CONFIRMED,
            ChoreDefinition.category == Category.REWARD,
        )
        .all()
    )
    return [
        EarningEntry(
            entry_type=EarningType.REWARD,
            amount_pence=definition.amount_pence,
            week_id=week.id,
            occurred_on=instance.due_date or week.end_date,
            reason=f"{definition.name}, earned in a week that was voided",
        )
        for instance, definition in rows
    ]


def stored_figures(week: Week) -> dict[str, int | str | None]:
    """Read a closed week's figures. Read, not recompute.

    Every value here comes from the week's own columns. No definition is
    consulted, which is why renaming or repricing a chore tomorrow cannot
    change what this returns.
    """
    return {
        "status": week.status.value,
        "chore_pay_pence": week.settled_basic_pence,
        "bonus_pence": week.settled_bonus_pence,
        "reward_pence": week.settled_reward_pence,
        "total_pence": week.settled_total_pence,
        "closed_at": week.closed_at.isoformat() if week.closed_at else None,
        "void_reason": week.void_reason,
    }


def open_weeks(session: Session) -> list[Week]:
    """Every week still open, oldest first. There may be several."""
    return (
        session.query(Week)
        .filter(Week.status == WeekStatus.OPEN)
        .order_by(Week.start_date)
        .all()
    )
