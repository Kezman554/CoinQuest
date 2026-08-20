"""the base allowance is its own component

The scheme pays a base allowance every week regardless of how the chores went,
and separately puts the chore pay at stake on them. Those were collapsed into
one column called settled_basic_pence, which was both the wrong name and one
figure short.

settled_basic_pence becomes settled_chore_pay_pence — what the chore pay came
to, all of it or nothing — and settled_base_pence joins it. A week's total is
now the sum of four things.

A void takes away the base, the chore pay and the bonuses. It does not take
away rewards: those were earned by something happening rather than by the week
going well, so they settle through the ordinary path and a voided week's total
is whatever they came to. The old constraint demanded a voided total of zero,
which would have forced rewards to be written somewhere else at void-time —
and a void is liftable until the week settles, so a reward written then would
be paid twice with an append-only ledger unable to take it back.

The two triggers on `weeks` are dropped and recreated. A batch rebuild
recreates the table, which would otherwise drop them silently, and they name
the renamed column anyway.

Revision ID: 4e720209aaba
Revises: 82826e03b64d
Create Date: 2026-08-20 19:11:24.416671

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = '4e720209aaba'
down_revision: Union[str, None] = '82826e03b64d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    for name in WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    # A rename, not a drop and an add: any figure already stored is the chore
    # pay and must stay attached to the week that stored it.
    op.execute("ALTER TABLE weeks RENAME COLUMN settled_basic_pence TO settled_chore_pay_pence")

    with op.batch_alter_table("weeks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("settled_base_pence", sa.Integer(), nullable=True))

    # Any week already closed was closed under a scheme with no separate base.
    op.execute("UPDATE weeks SET settled_base_pence = 0 WHERE status <> 'open'")

    # Rebuild from the model, which carries the new constraint set. SQLite
    # cannot alter or drop a CHECK any other way.
    # SQLite cannot alter or drop a CHECK, so the table is rebuilt from the
    # model, which carries the new constraint set. copy_from supplies the new
    # shape; the alter_column below is a no-op whose only job is to give the
    # batch something to do, because an empty batch does not rebuild anything.
    with op.batch_alter_table(
        "weeks", schema=None, copy_from=_weeks_table(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("settled_total_pence", existing_type=sa.Integer())

    for statement in WEEKS_TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table("weeks", schema=None) as batch_op:
        batch_op.drop_column("settled_base_pence")

    op.execute("ALTER TABLE weeks RENAME COLUMN settled_chore_pay_pence TO settled_basic_pence")


def _weeks_table():
    """The weeks table as the models now define it."""
    from app.models.weeks import Week

    return Week.__table__
