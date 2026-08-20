"""a deposit is not capped by one week's total

A week can owe more than it settled for. A parent-entered reward belongs to
the week it was entered in and is independent of the chore result, so it never
touches the week's settled figures — but it is still money handed over on
payday, and the child may put it in the bank.

The cap that mattered was never this one. What a deposit may not exceed is
what was actually paid across every week the payment cleared, and only the
payment knows that. The database keeps the part it can see: not negative.

The two triggers on `weeks` are dropped and recreated around the rebuild.

Revision ID: 9040ce063e24
Revises: 4e720209aaba
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models

# revision identifiers, used by Alembic.
revision: str = '9040ce063e24'
down_revision: Union[str, None] = '4e720209aaba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Repeated here rather than imported: a migration is a record of what was run,
# and must not change meaning later because another file did.
WEEKS_TRIGGERS = {
    "settled_week_figures_are_final": """
        CREATE TRIGGER settled_week_figures_are_final
        BEFORE UPDATE ON weeks
        FOR EACH ROW WHEN OLD.status IN ('settled', 'voided') AND (
               NEW.status                  IS NOT OLD.status
            OR NEW.start_date              IS NOT OLD.start_date
            OR NEW.end_date                IS NOT OLD.end_date
            OR NEW.settled_base_pence      IS NOT OLD.settled_base_pence
            OR NEW.settled_chore_pay_pence IS NOT OLD.settled_chore_pay_pence
            OR NEW.settled_bonus_pence     IS NOT OLD.settled_bonus_pence
            OR NEW.settled_reward_pence    IS NOT OLD.settled_reward_pence
            OR NEW.settled_total_pence     IS NOT OLD.settled_total_pence
            OR NEW.closed_at               IS NOT OLD.closed_at
        )
        BEGIN
            SELECT RAISE(ABORT,
                'a settled or voided week is closed forever; its figures cannot change');
        END
    """,
    "a_closed_week_is_not_deleted": """
        CREATE TRIGGER a_closed_week_is_not_deleted
        BEFORE DELETE ON weeks
        FOR EACH ROW WHEN OLD.status IN ('settled', 'voided')
        BEGIN
            SELECT RAISE(ABORT, 'a closed week cannot be deleted');
        END
    """,
}


def _weeks_table():
    from app.models.weeks import Week

    return Week.__table__


def upgrade() -> None:
    for name in WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    # SQLite cannot drop a CHECK; the table is rebuilt from the model. The
    # alter_column is a no-op that gives the batch something to do, because an
    # empty batch does not rebuild.
    with op.batch_alter_table(
        "weeks", schema=None, copy_from=_weeks_table(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("deposited_pence", existing_type=sa.Integer())

    for statement in WEEKS_TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    # The old constraint cannot be restored without rejecting rows that are
    # now legitimate, so this leaves the relaxed one in place deliberately.
    pass
