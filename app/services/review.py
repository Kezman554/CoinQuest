"""Ruling on a batch of claims.

Lifted out of the router because two callers now need it and they must not
drift apart. `POST /api/claims/review` applies a batch for real, and the
parent view asks what a batch *would* do before anybody types a PIN. A preview
computed by different code from the commit is not a preview — it is a second
opinion, and the moment the two disagree the number a parent agreed to is not
the number that happened.

So both go through `apply_decisions`. The preview runs it inside a savepoint
and throws the savepoint away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.models.chores import ChoreInstance
from app.models.enums import InstanceState, WeekStatus
from app.models.weeks import Week
from app.services.authorisation import Authorisation


class ReviewError(Exception):
    """A decision in the batch cannot be applied.

    Carries the instance that stopped it, so the caller can name the item
    rather than making a parent work out which half of their batch went
    through — the answer being neither, because nothing is committed until
    every decision has applied.
    """

    def __init__(self, message: str, instance_id: int) -> None:
        super().__init__(message)
        self.instance_id = instance_id


@dataclass(frozen=True)
class Decision:
    """One ruling on one claim."""

    instance_id: int
    decision: Literal["confirm", "reject"]


@dataclass(frozen=True)
class Applied:
    confirmed: tuple[int, ...]
    rejected: tuple[int, ...]


def load(session: Session, instance_id: int) -> ChoreInstance:
    instance = session.get(ChoreInstance, instance_id)
    if instance is None:
        raise ReviewError(f"No chore instance {instance_id}.", instance_id)
    return instance


def apply_decisions(
    session: Session,
    decisions: list[Decision],
    authorisation: Authorisation,
) -> Applied:
    """Apply every decision to the session. Commits nothing.

    The caller commits, or rolls back, or throws away a savepoint. Keeping
    that out of here is what lets one batch be atomic and the same code be
    used to answer a question without answering it permanently.
    """
    confirmed: list[int] = []
    rejected: list[int] = []

    for decision in decisions:
        instance = load(session, decision.instance_id)
        _refuse_closed_weeks(session, instance)

        if instance.state is not InstanceState.CLAIMED:
            raise ReviewError(
                f"Instance {instance.id} is {instance.state.value}, not a"
                " pending claim. Nothing in this batch was applied.",
                instance.id,
            )

        if decision.decision == "confirm":
            confirm(instance, authorisation)
            confirmed.append(instance.id)
        else:
            reject(instance, authorisation)
            rejected.append(instance.id)

    session.flush()
    return Applied(confirmed=tuple(confirmed), rejected=tuple(rejected))


def _refuse_closed_weeks(session: Session, instance: ChoreInstance) -> None:
    """A settled or voided week is closed forever, including to a claim."""
    week = session.get(Week, instance.week_id)
    if week is not None and week.status is not WeekStatus.OPEN:
        raise ReviewError(
            f"Week {week.start_date.isoformat()} is {week.status.value};"
            " it cannot be changed.",
            instance.id,
        )


def confirm(instance: ChoreInstance, authorisation: Authorisation) -> None:
    instance.state = InstanceState.CONFIRMED
    instance.confirmed_at = authorisation.at
    # Who agreed it. There is one parent today; recording it anyway means the
    # history is already right on the day there are two.
    instance.authorised_by = authorisation.party


def reject(instance: ChoreInstance, authorisation: Authorisation) -> None:
    """A rejected claim goes back to untouched, not to missed.

    Not believing a claim is not the same as ruling the chore was not done,
    and the difference matters: an untouched instance is provisional until
    settlement, so the child can still do it, or claim it again, before the
    week closes.

    The rejection is recorded even though no rule reads it. Without it a
    refused claim looks exactly like a tap that never registered, and the
    child re-claims into the same refusal without ever being told why.
    """
    instance.state = InstanceState.UNTOUCHED
    instance.claimed_at = None
    instance.rejected_at = authorisation.at
    instance.rejection_count += 1
    instance.authorised_by = authorisation.party
