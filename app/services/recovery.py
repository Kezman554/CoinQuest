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
from dataclasses import dataclass, field
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
    cap: int = RECOVERY_CAP
    _by_id: dict[int, Requirement] = field(default_factory=dict, repr=False)

    def requirement(self, definition_id: int) -> Requirement | None:
        return self._by_id.get(definition_id)

    @property
    def chore_pay_at_stake_pence(self) -> int:
        """What the chore pay is worth: paid whole, or not at all.

        Not the base allowance, which is paid every week whatever happens here
        and is not the recovery rules' business.
        """
        return sum(
            requirement.amount_pence
            for requirement in self.requirements
            if requirement.category is Category.BASIC and requirement.is_assessed
        )

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
    cap: int = RECOVERY_CAP,
) -> WeekAssessment:
    """Work out what the week asked for, what it got, and what it missed.

    Pure. `plan` carries the requirement — already reduced by whatever the
    waivers did — and `instances` carries what happened.
    """
    definitions = list(definitions)  # read twice below; a generator would empty
    confirmed: dict[int, int] = {}
    marked: dict[int, list] = {}
    untouched: dict[int, list] = {}
    present: dict[int, int] = {}

    for instance in instances:
        present[instance.definition_id] = present.get(instance.definition_id, 0) + 1
        if instance.state is InstanceState.CONFIRMED:
            confirmed[instance.definition_id] = (
                confirmed.get(instance.definition_id, 0) + instance.quantity
            )
        elif instance.state is InstanceState.MISSED:
            marked.setdefault(instance.definition_id, []).append(instance)
        else:
            # Untouched, or claimed and never confirmed. A claim is a request
            # to be believed, and nobody believed it in time.
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
        cap=cap,
        _by_id={requirement.definition_id: requirement for requirement in requirements},
    )


def _misses_for(requirement: Requirement, marked: Sequence, untouched: Sequence) -> list[Miss]:
    """Name the shortfall, taking the decided misses before the inferred ones.

    The shortfall is the number of misses. Instances marked missed by a parent
    fill it first, because those are decisions already made; whatever is left
    is inferred here, from nothing having happened. If a parent marked more
    missed than the week ended up short of — which a later waiver can cause —
    the extra ones simply do not become misses. The requirement was met.
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
