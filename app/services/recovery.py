"""Misses, recoveries, and the assignment that pays the child most.

Three ideas, in order.

**Assessment is against the requirement, never against a count of rows.** The
week asks for a chore a certain number of times; the question is whether that
many were confirmed. It is deliberately not "how many instances exist", because
a waiver applied after work was confirmed leaves a confirmed instance the plan
no longer asks for. That surplus has to be harmless, and it is harmless only
under the first question. Doing more than was asked is never a problem.

**A miss is either decided or inferred.** A parent marking a chore missed is a
decision, definite when made, and it names them. A miss established here is the
absence of anything having happened: nobody decided it, so it has no author.
Both are misses; they are not the same fact.

**The computed answer is a proposal, not a verdict.** Settlement proposes and
nothing settles until a parent agrees, so a parent may hand back a different
assignment from the one worked out here — including one that pays less. A
passed week can be worth more to a child than the fifty pence it cost, and
that is a judgement no optimiser is entitled to make. What a supplied
assignment does not get is trust: it is checked against the same rules as any
other, because a parent may choose to lose money and may not choose to break
the scheme. See `assignment_from`.

**Recovery is an optimisation, so it is computed.** A missed basic chore may be
recovered by having completed a bonus chore, forgone unpaid. Which bonus to
spend is a real choice with real money on it, and the obvious answer is wrong
often enough to matter — spending a 300p bonus to rescue the chore pay when a
100p one would have done costs 200p, and spending anything at all when the
misses exceed the cap costs the lot for nothing. The search space is a handful
of chores, so every assignment is evaluated and the best one wins. Nobody has
to reason about ordering, and ordering can never cost the child money.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations

from app.models.base import utcnow
from app.models.enums import (
    ON_DEMAND_CADENCES,
    WEEK_DERIVED_CADENCES,
    Cadence,
    Category,
    InstanceState,
    MissOrigin,
)
from app.services.instances import WeekPlan

#: How many misses one week may recover. Beyond this the chore pay fails: the
#: recovery route exists to catch a bad day, not to make the basics optional.
#: A number, in one place, because it will be argued about and changed.
RECOVERY_CAP = 2


@dataclass(frozen=True)
class Requirement:
    """What the week asked of one chore, and what actually happened."""

    definition_id: int
    name: str
    category: Category
    cadence: Cadence
    amount_pence: int
    required: int
    confirmed: int
    marked_missed: int = 0

    @property
    def met(self) -> bool:
        """Was the requirement satisfied? More than asked for still counts."""
        return self.confirmed >= self.required

    @property
    def shortfall(self) -> int:
        """How many occasions short, never below zero.

        The floor is what makes a surplus harmless. A confirmed instance the
        plan stopped asking for cannot push this negative and quietly buy off
        a miss somewhere else.
        """
        return max(self.required - self.confirmed, 0)

    @property
    def is_assessed(self) -> bool:
        """A chore the week did not ask for cannot be missed or completed."""
        return self.required > 0

    @property
    def can_be_spent_as_recovery(self) -> bool:
        """Could this be started today, by the child, on being told?

        Derived from the cadence and from nothing else. No chore is named
        anywhere in this rule, so adding one to the scheme never means
        remembering to come back here.
        """
        return (
            self.category is Category.BONUS
            and self.cadence in ON_DEMAND_CADENCES
            and self.met
        )


@dataclass(frozen=True)
class Miss:
    """One occasion the week asked for and did not get."""

    definition_id: int
    name: str
    origin: MissOrigin
    instance_id: int | None = None

    @property
    def is_definite(self) -> bool:
        return self.origin is MissOrigin.PARENT_MARKED


@dataclass(frozen=True)
class Assignment:
    """One way of spending completed bonus chores to cover the misses."""

    spent_definition_ids: tuple[int, ...]
    chore_pay_pence: int
    bonus_pay_pence: int
    reward_pence: int
    misses_recovered: int
    misses_outstanding: int

    @property
    def total_pence(self) -> int:
        return self.chore_pay_pence + self.bonus_pay_pence + self.reward_pence

    @property
    def chore_pay_failed(self) -> bool:
        return self.misses_outstanding > 0


@dataclass(frozen=True)
class WeekAssessment:
    """Everything settlement needs to know about a week, before it decides."""

    requirements: tuple[Requirement, ...]
    misses: tuple[Miss, ...]
    reward_pence: int
    #: The household's one weekly basic pot, in pence — see
    #: chore_pay_at_stake_pence. Required, not defaulted: a wrong silent
    #: default here is a wrong figure of real money, so every caller supplies
    #: it deliberately (app.services.settlement.propose reads it from
    #: app.models.settings.SchemeSettings when the caller does not override
    #: it, the same pattern base_pence already uses).
    weekly_basic_pay_pence: int
    cap: int = RECOVERY_CAP
    _by_id: dict[int, Requirement] = field(default_factory=dict, repr=False)

    def requirement(self, definition_id: int) -> Requirement | None:
        return self._by_id.get(definition_id)

    @property
    def chore_pay_at_stake_pence(self) -> int:
        """What the chore pay is worth: paid whole, or not at all.

        Not the base allowance, which is paid every week whatever happens here
        and is not the recovery rules' business.

        Not a sum of the individual basic chores' own amounts, either. A
        basic chore carries no amount of its own any more — it only gates
        whether the household's one weekly basic pot pays out. "Make bed" and
        "Lunchbox and cups" both being basic chores never meant £2 + £2; the
        rules describe one £2, and the definitions collectively decide
        whether it is earned. See app.models.settings.SchemeSettings.
        """
        any_assessed = any(
            requirement.category is Category.BASIC and requirement.is_assessed
            for requirement in self.requirements
        )
        return self.weekly_basic_pay_pence if any_assessed else 0

    @property
    def completed_bonuses(self) -> tuple[Requirement, ...]:
        return tuple(
            requirement
            for requirement in self.requirements
            if requirement.category is Category.BONUS
            and requirement.is_assessed
            and requirement.met
        )

    @property
    def spendable_bonuses(self) -> tuple[Requirement, ...]:
        """Completed bonus chores a miss could actually be recovered with."""
        return tuple(
            requirement
            for requirement in self.completed_bonuses
            if requirement.can_be_spent_as_recovery
        )


def assess_week(
    plan: WeekPlan,
    definitions: Iterable,
    instances: Iterable,
    *,
    weekly_basic_pay_pence: int,
    cap: int = RECOVERY_CAP,
    for_display: bool = False,
) -> WeekAssessment:
    """Work out what the week asked for, what it got, and what it missed.

    Pure. `plan` carries the requirement — already reduced by whatever the
    waivers did — and `instances` carries what happened. `weekly_basic_pay_pence`
    has no default on purpose — see WeekAssessment's own field.

    `for_display` is the one flag in this module that is never for settling.
    It answers a different question from the default assessment: not "what
    would this week pay if it ended right now", but "where does the child
    stand, reading this before anyone has ruled anything out". Two things
    change under it, both already true of an actual settlement's own rule
    that misses become real only when something makes them real:

    - A claim counts toward what was confirmed, the moment it is made. A
      parent's confirmation is not what moves this figure; a parent's
      rejection is, because a rejection reverts the instance to untouched.
    - An instance nobody has ruled on is not a miss. Only a miss a parent
      has actually marked counts against the week — exactly the set
      `Miss.is_definite` already names, and exactly what the recovery panel
      has used since Session I for the same reason: telling a child on
      Monday that Thursday is already lost would be untrue.

    With the flag off, this is the assessment settlement actually uses:
    everything still untouched becomes an inferred miss, which is what makes
    `record_inferred_misses` correct when a week is actually closed.
    """
    definitions = list(definitions)  # read twice below; a generator would empty
    confirmed: dict[int, int] = {}
    marked: dict[int, list] = {}
    untouched: dict[int, list] = {}
    present: dict[int, int] = {}

    for instance in instances:
        present[instance.definition_id] = present.get(instance.definition_id, 0) + 1
        counted = instance.state is InstanceState.CONFIRMED or (
            for_display and instance.state is InstanceState.CLAIMED
        )
        if counted:
            confirmed[instance.definition_id] = (
                confirmed.get(instance.definition_id, 0) + instance.quantity
            )
        elif instance.state is InstanceState.MISSED:
            marked.setdefault(instance.definition_id, []).append(instance)
        else:
            # Untouched, or claimed and never confirmed (and not for_display).
            # A claim is a request to be believed, and nobody believed it in
            # time — except when scoring for display, where believing it is
            # exactly the point until a parent rejects it.
            untouched.setdefault(instance.definition_id, []).append(instance)

    required = plan.required
    requirements: list[Requirement] = []
    misses: list[Miss] = []

    for definition in sorted(definitions, key=lambda d: (d.name, d.id)):
        if definition.cadence in WEEK_DERIVED_CADENCES:
            asked_for = required.get(definition.id, 0)
        else:
            # A one-off or an event is not predictable from a definition, so
            # the plan says nothing about it. Each instance was put there
            # deliberately by a parent, which is what the requirement is.
            asked_for = present.get(definition.id, 0)

        requirement = Requirement(
            definition_id=definition.id,
            name=definition.name,
            category=definition.category,
            cadence=definition.cadence,
            amount_pence=definition.amount_pence,
            required=asked_for,
            confirmed=confirmed.get(definition.id, 0),
            marked_missed=len(marked.get(definition.id, ())),
        )
        requirements.append(requirement)

        if requirement.category is not Category.BASIC or not requirement.shortfall:
            continue

        misses.extend(
            _misses_for(
                requirement,
                marked.get(definition.id, []),
                untouched.get(definition.id, []),
                # For display, nothing is inferred from bare silence — only a
                # miss a parent actually marked counts. See for_display above.
                infer_remainder=not for_display,
            )
        )

    # A reward is an event, not a requirement: each confirmed one pays its own
    # amount. This is the one place counting instances is the right question.
    reward_pence = sum(
        definition.amount_pence * confirmed.get(definition.id, 0)
        for definition in definitions
        if definition.category is Category.REWARD
    )

    return WeekAssessment(
        requirements=tuple(requirements),
        misses=tuple(misses),
        reward_pence=reward_pence,
        weekly_basic_pay_pence=weekly_basic_pay_pence,
        cap=cap,
        _by_id={requirement.definition_id: requirement for requirement in requirements},
    )


def _misses_for(
    requirement: Requirement,
    marked: Sequence,
    untouched: Sequence,
    *,
    infer_remainder: bool = True,
) -> list[Miss]:
    """Name the shortfall, taking the decided misses before the inferred ones.

    The shortfall is the number of misses. Instances marked missed by a parent
    fill it first, because those are decisions already made; whatever is left
    is inferred here, from nothing having happened. If a parent marked more
    missed than the week ended up short of — which a later waiver can cause —
    the extra ones simply do not become misses. The requirement was met.

    `infer_remainder=False` stops there: whatever shortfall marked misses do
    not cover is left alone rather than inferred from silence. That is the
    for_display case — see assess_week — and it must actually stop, not just
    run dry of instances to point at: a plain untouched instance still exists
    to loop over, so skipping the loop is the only way display scoring does
    not quietly manufacture a miss with no author and no row.
    """
    misses: list[Miss] = []
    outstanding = requirement.shortfall

    for instance in marked[:outstanding]:
        misses.append(
            Miss(
                definition_id=requirement.definition_id,
                name=requirement.name,
                origin=MissOrigin.PARENT_MARKED,
                instance_id=instance.id,
            )
        )

    if not infer_remainder:
        return misses

    remaining = outstanding - len(misses)
    candidates = list(untouched)
    for index in range(remaining):
        instance = candidates[index] if index < len(candidates) else None
        misses.append(
            Miss(
                definition_id=requirement.definition_id,
                name=requirement.name,
                origin=MissOrigin.INFERRED_AT_SETTLEMENT,
                instance_id=instance.id if instance is not None else None,
            )
        )

    return misses


@dataclass(frozen=True)
class MakeGood:
    """The route back from a miss, and what the week pays if it is taken.

    Not a rule of its own. It is the same optimiser run once more against a
    week that has not happened yet — "if these bonus chores were completed,
    what would `best_assignment` do with them" — so the all-or-nothing chore
    pay, the cap and the optimiser's own refusal to spend a bonus worth more
    than it rescues all apply to it without being restated anywhere.

    `restores_to_pence` is what that hypothetical week comes to, in the same
    currency as the assignment it was compared against — no base allowance
    (see `settlement.propose`, which adds it before the figure reaches a
    screen).
    """

    definition_ids: tuple[int, ...]
    names: tuple[str, ...]
    restores_to_pence: int


def best_make_good(
    assessment: WeekAssessment, assignment: Assignment
) -> MakeGood | None:
    """What the child could still do to get the chore pay back, if anything.

    Returns None rather than an empty encouragement whenever there is no real
    route: nothing is currently lost, the misses are past the cap and no
    amount of work recovers them, there are not enough bonus chores left
    undone to cover what is outstanding, or the best available swap does not
    actually pay more than doing nothing. A screen showing "you could still
    fix this" over a week that cannot be fixed is worse than a screen saying
    nothing at all.

    Only a chore the child could start today counts as a route —
    `ON_DEMAND_CADENCES`, the same test `can_be_spent_as_recovery` applies to
    the ones already completed. Telling him to go and do a week-long
    condition on Friday is not advice.
    """
    if not assignment.chore_pay_failed:
        return None
    if len(assessment.misses) > assessment.cap:
        return None

    outstanding = assignment.misses_outstanding
    candidates = tuple(
        requirement
        for requirement in assessment.requirements
        if requirement.category is Category.BONUS
        and requirement.cadence in ON_DEMAND_CADENCES
        and requirement.is_assessed
        and not requirement.met
    )
    if outstanding == 0 or outstanding > len(candidates):
        return None

    best: MakeGood | None = None
    for combination in combinations(candidates, outstanding):
        result = best_assignment(_as_if_completed(assessment, combination))
        # It has to actually clear the week and actually pay more. The
        # optimiser is free to decide that spending a 300p bonus to rescue a
        # 200p pot is a loss, and when it does, this is not a route back.
        if result.misses_outstanding > 0:
            continue
        if result.total_pence <= assignment.total_pence:
            continue
        if best is None or result.total_pence > best.restores_to_pence:
            best = MakeGood(
                definition_ids=tuple(
                    requirement.definition_id for requirement in combination
                ),
                names=tuple(requirement.name for requirement in combination),
                restores_to_pence=result.total_pence,
            )

    return best


def _as_if_completed(
    assessment: WeekAssessment, done: Sequence[Requirement]
) -> WeekAssessment:
    """The same week, with these chores treated as having been completed.

    A copy, scored and thrown away. Nothing here writes anything, and the
    misses are carried across untouched — completing a bonus chore never
    changes what the basics asked for.
    """
    ids = {requirement.definition_id for requirement in done}
    requirements = tuple(
        replace(requirement, confirmed=requirement.required)
        if requirement.definition_id in ids
        else requirement
        for requirement in assessment.requirements
    )
    return WeekAssessment(
        requirements=requirements,
        misses=assessment.misses,
        reward_pence=assessment.reward_pence,
        weekly_basic_pay_pence=assessment.weekly_basic_pay_pence,
        cap=assessment.cap,
        _by_id={
            requirement.definition_id: requirement for requirement in requirements
        },
    )


def evaluate(assessment: WeekAssessment, spent: Sequence[Requirement]) -> Assignment:
    """Score one candidate assignment of bonus chores to misses."""
    spent_ids = tuple(sorted(requirement.definition_id for requirement in spent))
    recovered = min(len(spent), len(assessment.misses))
    outstanding = len(assessment.misses) - recovered

    # Beyond the cap nothing is recoverable, however many bonus chores were
    # completed. The route exists to catch a bad day, not to make the basics
    # optional.
    if len(assessment.misses) > assessment.cap:
        recovered = 0
        outstanding = len(assessment.misses)

    chore_pay = assessment.chore_pay_at_stake_pence if outstanding == 0 else 0

    # A bonus chore is paid or spent, never both.
    bonus_pay = sum(
        requirement.amount_pence
        for requirement in assessment.completed_bonuses
        if requirement.definition_id not in spent_ids
    )

    return Assignment(
        spent_definition_ids=spent_ids,
        chore_pay_pence=chore_pay,
        bonus_pay_pence=bonus_pay,
        reward_pence=assessment.reward_pence,
        misses_recovered=recovered,
        misses_outstanding=outstanding,
    )


def all_assignments(assessment: WeekAssessment) -> list[Assignment]:
    """Every lawful way of spending the week's completed bonus chores.

    Sizes from nothing up to the cap. Spending more than there are misses is
    never worth anything, so those combinations are not generated; spending
    fewer is generated, because when the misses exceed the cap the answer is
    to spend nothing at all and that has to be a candidate.
    """
    spendable = assessment.spendable_bonuses
    ceiling = min(assessment.cap, len(assessment.misses), len(spendable))

    return [
        evaluate(assessment, combination)
        for size in range(ceiling + 1)
        for combination in combinations(spendable, size)
    ]


def best_assignment(assessment: WeekAssessment) -> Assignment:
    """The assignment paying the most.

    Ties are broken by spending fewer chores, then by the lower definition
    ids, so the same week always settles to the same answer — a settlement is
    a stored figure and must not depend on dictionary ordering.
    """
    return max(
        all_assignments(assessment),
        key=lambda assignment: (
            assignment.total_pence,
            -len(assignment.spent_definition_ids),
            tuple(-i for i in assignment.spent_definition_ids),
        ),
    )


def _times(count: int) -> str:
    """"once", "twice", or "5 times". These messages are read by a parent on a
    kitchen wall, not by anybody looking at a stack trace."""
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


def _misses(count: int) -> str:
    return "1 miss" if count == 1 else f"{count} misses"


class InvalidAssignment(ValueError):
    """A supplied assignment breaks a rule, rather than merely losing money.

    Losing money is allowed and is the whole reason this door exists. Spending
    a chore that was never done, spending one twice, recovering a miss that did
    not happen, or going past the cap are not choices — they are claims about
    the week that are untrue.
    """


@dataclass(frozen=True)
class SuppliedRecovery:
    """A parent's instruction: spend this chore to cover a miss of that one."""

    spend_definition_id: int
    for_definition_id: int


def assignment_from(
    assessment: WeekAssessment, supplied: Sequence[SuppliedRecovery]
) -> Assignment:
    """Score an assignment a parent supplied, after checking it is lawful.

    Every rule the computed assignment obeys is checked here too, against the
    same assessment of the same week. The only thing a parent is allowed to do
    that the optimiser will not is choose a worse answer.
    """
    if len(supplied) > assessment.cap:
        raise InvalidAssignment(
            f"At most {_misses(assessment.cap)} may be recovered in a week;"
            f" this assignment recovers {len(supplied)}."
        )

    spendable = {
        requirement.definition_id: requirement
        for requirement in assessment.spendable_bonuses
    }

    spent: list[Requirement] = []
    seen: set[int] = set()
    for recovery in supplied:
        requirement = assessment.requirement(recovery.spend_definition_id)

        if requirement is None:
            raise InvalidAssignment(
                f"There is no chore {recovery.spend_definition_id} in this week."
            )
        if recovery.spend_definition_id in seen:
            raise InvalidAssignment(
                f"{requirement.name!r} is spent twice; a bonus chore is paid or"
                " spent, never both, and never twice."
            )
        if requirement.category is not Category.BONUS:
            raise InvalidAssignment(
                f"{requirement.name!r} is not a bonus chore, so it cannot be"
                " spent to recover anything."
            )
        if not requirement.is_assessed or not requirement.met:
            raise InvalidAssignment(
                f"{requirement.name!r} was not completed this week, so there is"
                " nothing to give up."
            )
        if recovery.spend_definition_id not in spendable:
            raise InvalidAssignment(
                f"{requirement.name!r} cannot be completed on demand, so it is"
                " not a recovery."
            )

        seen.add(recovery.spend_definition_id)
        spent.append(requirement)

    _check_the_misses_exist(assessment, supplied)
    return evaluate(assessment, spent)


def _check_the_misses_exist(
    assessment: WeekAssessment, supplied: Sequence[SuppliedRecovery]
) -> None:
    """A recovery has to be for a miss that actually happened.

    Counted per chore rather than merely "there were some misses": recovering
    two misses of a chore that was missed once is as untrue as inventing one.
    """
    available: dict[int, int] = {}
    for miss in assessment.misses:
        available[miss.definition_id] = available.get(miss.definition_id, 0) + 1

    wanted: dict[int, int] = {}
    for recovery in supplied:
        wanted[recovery.for_definition_id] = (
            wanted.get(recovery.for_definition_id, 0) + 1
        )

    for definition_id, count in wanted.items():
        requirement = assessment.requirement(definition_id)
        name = requirement.name if requirement else f"chore {definition_id}"
        happened = available.get(definition_id, 0)
        if happened < count:
            if happened == 0:
                raise InvalidAssignment(
                    f"{name!r} was not missed this week, so there is nothing"
                    " there to recover."
                )
            raise InvalidAssignment(
                f"{name!r} was missed {_times(happened)} this week;"
                f" {_misses(count)} cannot be recovered."
            )


def record_inferred_misses(session, misses: Iterable[Miss]) -> int:
    """Write the inferred misses onto their instances. Returns how many.

    `authorised_by` is cleared rather than filled in. Nobody authorised an
    absence, and if the child had a claim rejected on this instance earlier in
    the week, that parent's name is still sitting there from the rejection —
    leaving it would read as though they had ruled it missed. The rejection
    itself survives in rejected_at and rejection_count, which is where that
    fact belongs.
    """
    from app.models.chores import ChoreInstance

    written = 0
    for miss in misses:
        if miss.origin is not MissOrigin.INFERRED_AT_SETTLEMENT:
            continue
        if miss.instance_id is None:
            continue  # a shortfall with no row to hang it on; the figure holds it
        instance = session.get(ChoreInstance, miss.instance_id)
        if instance is None or instance.state is InstanceState.MISSED:
            continue
        instance.state = InstanceState.MISSED
        instance.missed_at = utcnow()
        instance.miss_origin = MissOrigin.INFERRED_AT_SETTLEMENT
        instance.authorised_by = None
        instance.claimed_at = None
        written += 1

    session.flush()
    return written
