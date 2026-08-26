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

A proposal is a proposal. The assignment of make-goods is worked out to pay the
most, and a parent may hand back a different one — including one that pays
less, because a passed week can be worth more to a child than the fifty pence
it cost. That is a judgement about a household, not about arithmetic, and it is
theirs. What they cannot do is break the scheme: a supplied assignment is
checked against the same rules as the computed one, and the week records that
it was overridden, by whom, and what the app would have paid instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.config import get_settings
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
from app.models.weeks import SettlementLine, Week, WeekReopening
from app.services import savings, scheme_settings
from app.services.authorisation import Authorisation
from app.services.calendar import Period, today
from app.services.instances import plan_week
from app.services.recovery import (
    RECOVERY_CAP,
    Assignment,
    Miss,
    Requirement,
    SuppliedRecovery,
    WeekAssessment,
    assess_week,
    assignment_from,
    best_assignment,
    record_inferred_misses,
)


class NotOpen(Exception):
    """The week is settled or voided. Closed is closed."""


class OverrideNeedsAReason(Exception):
    """An override that pays less than the app offered, and says nothing.

    The turned-down figure is stored precisely so the difference between the
    two tells a story. Left without a reason it tells half of one, and the
    half it leaves out is the only part a person could not work out for
    themselves a year later.
    """


class ProposalChanged(Exception):
    """The week is no longer worth what the parent agreed to.

    Raised when the figure submitted with the agreement does not match the
    figure the week currently proposes — because a claim was confirmed, or a
    waiver added, between the parent reading the proposal and agreeing it.
    Settling anyway would store an amount nobody actually agreed.
    """


class NotClosed(Exception):
    """Only a closed week can be reopened. This one is still open."""


class NotTheLatestSettledWeek(Exception):
    """A week with any settled week after it cannot be reopened.

    Reopening an earlier week while a later one already stands settled would
    leave two weeks disagreeing about which one is "now", with no way to make
    that make sense. Only the most recent settled week is eligible, so a
    correction always unwinds in the same order it happened.
    """


class ReopenNeedsAReason(Exception):
    """Reopening a settled week is unusual enough to want a reason, always.

    Blank or whitespace counts as none — the same standard an override that
    costs money is already held to.
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
    """One line of the week's figures, ready to be frozen into the record.

    definition_id is usually one chore's, but not always: the weekly basic
    pay is one pot several chores gate rather than any one chore's own
    amount, so its line names none of them — see _lines() below. Null here
    means the same thing SettlementLine.source_definition_id already means
    for a deleted definition: provenance absent, not a chore that vanished.
    """

    definition_id: int | None
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

    Four components, and the first two are easy to confuse:

    `base_pence` is the weekly allowance. It is paid every week regardless of
    how the chores went — a bad week at the hoover never touches it — and only
    a voided week removes it.

    `chore_pay_at_stake_pence` is what the basic chores were collectively
    worth, and `chore_pay_pence` is what that came to: all of it or nothing. It
    is never apportioned. A week whose misses cannot be recovered pays no chore
    pay at all, which is the rule the recovery route exists to soften.
    """

    week_id: int
    start_date: date
    end_date: date
    base_pence: int
    chore_pay_at_stake_pence: int
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

    #: True when the assignment came from a parent rather than the optimiser.
    overridden: bool = False

    #: What the computed assignment would have been worth. The same as
    #: total_pence when nobody overrode anything, and the other half of the
    #: story when somebody did.
    optimum_total_pence: int = 0

    @property
    def foregone_pence(self) -> int:
        """What the override costs, if it costs anything.

        Never negative: an override that happens to pay more than the computed
        assignment is impossible, since the computed one is the best available
        by construction.
        """
        return max(self.optimum_total_pence - self.total_pence, 0)

    @property
    def chore_pay_awarded(self) -> bool:
        return self.chore_pay_pence > 0 or self.chore_pay_at_stake_pence == 0

    @property
    def misses_outstanding(self) -> int:
        return len(self.misses) - len(self.recoveries)


def week_period(week: Week, tz) -> Period:
    return Period(start=week.start_date, end=week.end_date, tz=tz)


def propose(
    session: Session,
    week: Week,
    tz,
    *,
    cap: int = RECOVERY_CAP,
    base_pence: int | None = None,
    weekly_basic_pay_pence: int | None = None,
    override: Sequence[SuppliedRecovery] | None = None,
    for_display: bool = False,
) -> Proposal:
    """Work out what an open week is worth. Writes nothing.

    Pass `override` to score an assignment a parent supplied instead of the
    computed one. It is validated against this week's assessment before it is
    scored, so it can lose money but cannot claim something untrue about the
    week. The computed figure is worked out either way and carried alongside.

    Refuses a closed week. That refusal is the whole guarantee: a settled
    week's figures are read from its own columns and there is no code path
    that would rebuild them from today's definitions.

    `for_display` is never for settling — it is for a screen reading where
    the week stands before anyone has ruled on everything. On, a claim
    counts toward the requirement the moment it is made, and nothing untouched
    counts against the child until a parent actually marks it missed; a miss
    otherwise becomes real only at settlement, and this is what lets a screen
    say so honestly mid-week rather than pricing in a miss nobody has decided
    yet. See `recovery.assess_week` for exactly what changes. `settle()` never
    passes this — it always calls `propose()` at its default, so what gets
    agreed and stored is the same pessimistic, final reckoning it always was.
    """
    if week.status is not WeekStatus.OPEN:
        raise NotOpen(
            f"Week {week.start_date.isoformat()} is {week.status.value}."
            " A closed week is read, never recomputed."
        )

    if base_pence is None:
        base_pence = get_settings().weekly_base_pence

    if weekly_basic_pay_pence is None:
        weekly_basic_pay_pence = scheme_settings.weekly_basic_pay_pence(session)

    definitions = session.query(ChoreDefinition).all()
    waivers = session.query(Waiver).all()
    instances = session.query(ChoreInstance).filter(ChoreInstance.week_id == week.id).all()

    plan = plan_week(week_period(week, tz), definitions, waivers, week_id=week.id)
    assessment = assess_week(
        plan,
        definitions,
        instances,
        weekly_basic_pay_pence=weekly_basic_pay_pence,
        cap=cap,
        for_display=for_display,
    )

    optimum = best_assignment(assessment)
    if override is None:
        assignment = optimum
        recoveries = _recoveries(assessment, assignment)
    else:
        # Raises InvalidAssignment, which the caller turns into a refusal.
        assignment = assignment_from(assessment, override)
        recoveries = _supplied_recoveries(assessment, override)

    lines = _lines(assessment, assignment)

    return Proposal(
        week_id=week.id,
        start_date=week.start_date,
        end_date=week.end_date,
        base_pence=base_pence,
        chore_pay_at_stake_pence=assessment.chore_pay_at_stake_pence,
        chore_pay_pence=assignment.chore_pay_pence,
        bonus_pence=assignment.bonus_pay_pence,
        reward_pence=assignment.reward_pence,
        total_pence=base_pence + assignment.total_pence,
        misses=assessment.misses,
        recoveries=recoveries,
        requirements=assessment.requirements,
        lines=lines,
        days_waived=plan.days_waived,
        cap=cap,
        overridden=override is not None,
        optimum_total_pence=base_pence + optimum.total_pence,
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


def _supplied_recoveries(
    assessment: WeekAssessment, supplied: Sequence[SuppliedRecovery]
) -> tuple[Recovery, ...]:
    """The parent's own pairing, kept as they gave it.

    Unlike the computed one this is not presentational: they said which chore
    covers which miss, and the record should say what they said.
    """
    return tuple(
        Recovery(
            miss_definition_id=recovery.for_definition_id,
            miss_name=_name_of(assessment, recovery.for_definition_id),
            spent_definition_id=recovery.spend_definition_id,
            spent_name=_name_of(assessment, recovery.spend_definition_id),
            forgone_pence=_amount_of(assessment, recovery.spend_definition_id),
        )
        for recovery in supplied
    )


def _name_of(assessment: WeekAssessment, definition_id: int) -> str:
    requirement = assessment.requirement(definition_id)
    return requirement.name if requirement else f"chore {definition_id}"


def _amount_of(assessment: WeekAssessment, definition_id: int) -> int:
    requirement = assessment.requirement(definition_id)
    return requirement.amount_pence if requirement else 0


def _lines(assessment: WeekAssessment, assignment: Assignment) -> tuple[ProposedLine, ...]:
    """Every chore the week assessed, and what it came to.

    Zero-value lines are kept. A basic chore that was missed, and a bonus
    chore worked and spent on a recovery, both happened, and a record that
    only lists what paid is not a record of the week.

    A basic chore's own line never carries an amount any more — it gates the
    shared pot rather than earning a slice of it, so nothing here is its
    "share". One further line, tied to no single chore, carries the pot
    itself (see _basic_pay_line below), so the record still explains where
    the chore pay came from and the lines still sum to the total — the same
    invariant test_every_stored_amount_is_an_integer_number_of_pence checks.
    """
    lines: list[ProposedLine] = []
    basic_requirements: list[Requirement] = []

    for requirement in assessment.requirements:
        if not requirement.is_assessed:
            continue

        if requirement.category is Category.BASIC:
            basic_requirements.append(requirement)
            if not requirement.met:
                note = "missed, recovered" if assignment.chore_pay_pence else "missed"
            else:
                note = None if assignment.chore_pay_pence else "the weekly basic pay was not earned"
            lines.append(
                ProposedLine(
                    definition_id=requirement.definition_id,
                    chore_name=requirement.name,
                    category=requirement.category,
                    cadence=requirement.cadence,
                    unit_amount_pence=0,
                    quantity=1,
                    amount_pence=0,
                    note=note,
                )
            )

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

    if basic_requirements:
        lines.append(_basic_pay_line(assessment, assignment))

    return tuple(lines)


def _basic_pay_line(assessment: WeekAssessment, assignment: Assignment) -> ProposedLine:
    """The shared pot itself, as its own line — tied to no single chore.

    Named apart from any definition (definition_id=None) because it is not
    one: it is what the basic chores collectively earned, or did not, and
    attributing it to any one of them would be exactly the invented fraction
    this whole change exists to stop doing. cadence=WEEKLY_CONDITION because
    that is the closest true description of what is happening to it — judged
    once, at settlement, the same as any week-long condition — not because it
    is one.
    """
    paid = assignment.chore_pay_pence
    return ProposedLine(
        definition_id=None,
        chore_name="Weekly basic pay",
        category=Category.BASIC,
        cadence=Cadence.WEEKLY_CONDITION,
        unit_amount_pence=assessment.weekly_basic_pay_pence,
        quantity=1,
        amount_pence=paid,
        note=None if paid else "not earned this week",
    )


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
    override_reason: str | None = None,
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

    if proposal.overridden and proposal.foregone_pence and not (override_reason or "").strip():
        raise OverrideNeedsAReason(
            f"This settles for {proposal.foregone_pence}p less than the"
            f" {proposal.optimum_total_pence}p the app worked out. Say why,"
            " so the week explains itself later."
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
    week.settled_base_pence = proposal.base_pence
    week.settled_chore_pay_pence = proposal.chore_pay_pence
    week.settled_bonus_pence = proposal.bonus_pence
    week.settled_reward_pence = proposal.reward_pence
    week.settled_total_pence = proposal.total_pence
    week.closed_at = authorisation.at

    if proposal.overridden:
        # Recorded so that a week paying less than it might have does not read,
        # a year from now, as though the app got its sums wrong. The figure
        # that was turned down is part of the record.
        week.overridden_by = authorisation.party
        week.override_reason = (override_reason or "").strip() or None
        week.optimum_total_pence = proposal.optimum_total_pence

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
    tz=None,
) -> Week:
    """Close a week paying nothing it had to earn, without erasing anything.

    A void takes away the three things that were contingent on the week going
    well: the base allowance, the chore pay and the bonuses. It does not take
    away rewards. Those were earned by something happening — an award, a
    kindness, a job nobody asked for — and a bad week does not unhappen them.

    So rewards settle here through exactly the same path as an ordinary
    settlement, and a voided week's total is whatever they came to. The
    alternative, writing them to the earnings ledger as a special case at
    void-time, would pay them twice if the void were ever lifted and the week
    then settled normally — and an append-only ledger cannot take that back.

    Every instance stays exactly as it is. Voiding is a statement about the
    money, not about the work.
    """
    if week.status is not WeekStatus.OPEN:
        raise NotOpen(f"Week {week.start_date.isoformat()} is already closed.")

    if not reason or not reason.strip():
        raise ValueError("Voiding a week is unusual enough to want a reason.")

    proposal = propose(session, week, tz or get_settings().tzinfo)

    # The reward lines survive; everything else about the week is set aside.
    for line in proposal.lines:
        if line.category is not Category.REWARD:
            continue
        session.add(
            SettlementLine(
                week_id=week.id,
                chore_name=line.chore_name,
                category=line.category,
                cadence=line.cadence,
                unit_amount_pence=line.unit_amount_pence,
                quantity=line.quantity,
                amount_pence=line.amount_pence,
                source_definition_id=line.definition_id,
                note="earned before the week was voided",
            )
        )

    week.status = WeekStatus.VOIDED
    week.settled_base_pence = 0
    week.settled_chore_pay_pence = 0
    week.settled_bonus_pence = 0
    week.settled_reward_pence = proposal.reward_pence
    week.settled_total_pence = proposal.reward_pence
    week.closed_at = authorisation.at
    week.void_reason = reason.strip()

    if proposal.reward_pence:
        session.add(
            EarningEntry(
                entry_type=EarningType.WEEK_SETTLEMENT,
                amount_pence=proposal.reward_pence,
                week_id=week.id,
                occurred_on=week.end_date,
                reason=f"Week {week.start_date.isoformat()} voided; rewards stand",
            )
        )

    session.flush()
    return week


def reopen(
    session: Session,
    week: Week,
    authorisation: Authorisation,
    *,
    reason: str,
    tz=None,
) -> Week:
    """Undo a settlement, deliberately and narrowly.

    "A settled week is a closed event" still holds — this is not a way
    around that, it is a single, named, authorised exception to it, for a
    parent's own mistake rather than a scheme change reaching backwards.

    Only the most recent settled week is eligible: a week with any settled
    week after it is refused, because reopening it while a later one stands
    settled would leave two weeks disagreeing about which one is "now".
    Checked here, not only at the caller, so nothing that calls this routine
    directly can route around it.

    If the week was paid, the payment is unwound too. paid_at and
    deposited_pence return to their never-paid state, and the savings ledger
    is corrected by appending a reversal entry for exactly the portion of a
    payment that had been apportioned to this week — `deposited_pence`
    already holds that share, whether or not the same payment also cleared
    other weeks.

    The week goes back to OPEN and nothing more. Settling it again goes
    through propose() and settle() exactly as any other open week would —
    this grants no shortcut through either.
    """
    if week.status is WeekStatus.OPEN:
        raise NotClosed(f"Week {week.start_date.isoformat()} is already open.")

    if not reason or not reason.strip():
        raise ReopenNeedsAReason("Reopening a settled week needs to say why.")

    later = (
        session.query(Week)
        .filter(Week.start_date > week.start_date, Week.status != WeekStatus.OPEN)
        .order_by(Week.start_date)
        .first()
    )
    if later is not None:
        raise NotTheLatestSettledWeek(
            f"Week {later.start_date.isoformat()} settled after this one and"
            " must be reopened first — only the most recent settled week can"
            " be reopened."
        )

    was_paid = week.paid_at is not None
    reversed_deposit_pence = 0
    reversal_entry_id: int | None = None
    if was_paid and week.deposited_pence:
        reversal = savings.record_reversal(
            session,
            amount_pence=week.deposited_pence,
            occurred_on=today(tz or get_settings().tzinfo),
            week_id=week.id,
            reason=(
                f"Reversed: week {week.start_date.isoformat()} was reopened"
                f" — {reason.strip()}"
            ),
        )
        reversed_deposit_pence = week.deposited_pence
        reversal_entry_id = reversal.id

    session.add(
        WeekReopening(
            week_id=week.id,
            reopened_by=authorisation.party,
            reopened_at=authorisation.at,
            reason=reason.strip(),
            previous_status=week.status,
            previous_base_pence=week.settled_base_pence,
            previous_chore_pay_pence=week.settled_chore_pay_pence,
            previous_bonus_pence=week.settled_bonus_pence,
            previous_reward_pence=week.settled_reward_pence,
            previous_total_pence=week.settled_total_pence,
            previous_closed_at=week.closed_at,
            previous_void_reason=week.void_reason,
            previous_overridden_by=week.overridden_by,
            previous_override_reason=week.override_reason,
            was_paid=was_paid,
            previous_paid_at=week.paid_at,
            previous_deposited_pence=week.deposited_pence,
            reversed_deposit_pence=reversed_deposit_pence,
            reversal_entry_id=reversal_entry_id,
        )
    )

    # The controlled path through the weeks trigger: every closing figure
    # cleared in this one flush, which is the only shape of change the
    # trigger permits on a closed week — see the migration that defines it.
    week.status = WeekStatus.OPEN
    week.settled_base_pence = None
    week.settled_chore_pay_pence = None
    week.settled_bonus_pence = None
    week.settled_reward_pence = None
    week.settled_total_pence = None
    week.closed_at = None
    week.void_reason = None
    week.overridden_by = None
    week.override_reason = None
    week.optimum_total_pence = None
    week.paid_at = None
    week.deposited_pence = None

    session.flush()
    return week


def current_lines(week: Week) -> list[SettlementLine]:
    """This week's lines from its current settlement, not its whole history.

    A settlement line is append-only and never deleted, so a week that has
    been reopened and settled again carries lines from both rounds forever —
    that is the record. But "what does this figure consist of" means the
    lines written since the last reopen, which is what this filters to.
    Never a source of money: `settled_total_pence` is still the only figure
    that matters, this only explains it.
    """
    if not week.reopenings:
        return list(week.settlement_lines)
    since = week.reopenings[-1].reopened_at
    return [line for line in week.settlement_lines if line.created_at > since]


def stored_figures(week: Week) -> dict[str, int | str | None]:
    """Read a closed week's figures. Read, not recompute.

    Every value here comes from the week's own columns. No definition is
    consulted, which is why renaming or repricing a chore tomorrow cannot
    change what this returns.
    """
    return {
        "status": week.status.value,
        "overridden_by": week.overridden_by,
        "override_reason": week.override_reason,
        "optimum_total_pence": week.optimum_total_pence,
        "base_pence": week.settled_base_pence,
        "chore_pay_pence": week.settled_chore_pay_pence,
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
