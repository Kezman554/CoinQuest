"""an override that costs money says why

The turned-down figure is stored beside the one that was paid so the
difference between them tells a story. An override that pays less and gives no
reason tells only the half a person could have worked out for themselves, and
the missing half is the one that matters a year later.

Enforced here as well as in the service, because "a settled week explains
itself" is the sort of rule that gets forgotten by the next caller.

The two triggers on `weeks` are dropped and recreated around the rebuild.

Revision ID: 3c1f6a2d9b74
Revises: 1eb8e8b3e4ae
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models

# revision identifiers, used by Alembic.
revision: str = '3c1f6a2d9b74'
down_revision: Union[str, None] = '1eb8e8b3e4ae'
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
            OR NEW.overridden_by           IS NOT OLD.overridden_by
            OR NEW.override_reason         IS NOT OLD.override_reason
            OR NEW.optimum_total_pence     IS NOT OLD.optimum_total_pence
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
    """The weeks table as this revision leaves it.

    Written out rather than imported from app.models: a migration that reads
    the live model rebuilds whatever the model happens to say today, which
    stops the revision running against an empty database the moment a later
    one adds a column.
    """
    return sa.Table(
        "weeks",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("settled_base_pence", sa.Integer()),
        sa.Column("settled_chore_pay_pence", sa.Integer()),
        sa.Column("settled_bonus_pence", sa.Integer()),
        sa.Column("settled_reward_pence", sa.Integer()),
        sa.Column("settled_total_pence", sa.Integer()),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("void_reason", sa.Text()),
        sa.Column("overridden_by", sa.String(length=60)),
        sa.Column("override_reason", sa.Text()),
        sa.Column("optimum_total_pence", sa.Integer()),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("deposited_pence", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_weeks"),
        sa.UniqueConstraint("start_date", name="uq_weeks_start_date"),
        sa.CheckConstraint(
            "CAST(strftime('%w', start_date) AS INTEGER) = 0",
            name="ck_weeks_starts_on_a_sunday",
        ),
        sa.CheckConstraint(
            "julianday(end_date) - julianday(start_date) = 6",
            name="ck_weeks_runs_seven_days",
        ),
        sa.CheckConstraint(
            "(status = 'open'"
            "   AND settled_total_pence IS NULL AND closed_at IS NULL)"
            " OR (status IN ('settled', 'voided')"
            "   AND settled_base_pence IS NOT NULL"
            "   AND settled_chore_pay_pence IS NOT NULL"
            "   AND settled_bonus_pence IS NOT NULL"
            "   AND settled_reward_pence IS NOT NULL"
            "   AND settled_total_pence IS NOT NULL"
            "   AND closed_at IS NOT NULL)",
            name="ck_weeks_closed_weeks_carry_their_figures",
        ),
        sa.CheckConstraint(
            "status <> 'voided' OR (settled_base_pence = 0"
            " AND settled_chore_pay_pence = 0 AND settled_bonus_pence = 0)",
            name="ck_weeks_a_voided_week_loses_base_chore_pay_and_bonuses",
        ),
        sa.CheckConstraint(
            "settled_base_pence IS NULL OR settled_base_pence >= 0",
            name="ck_weeks_base_not_negative",
        ),
        sa.CheckConstraint(
            "settled_chore_pay_pence IS NULL OR settled_chore_pay_pence >= 0",
            name="ck_weeks_chore_pay_not_negative",
        ),
        sa.CheckConstraint(
            "settled_bonus_pence IS NULL OR settled_bonus_pence >= 0",
            name="ck_weeks_bonus_not_negative",
        ),
        sa.CheckConstraint(
            "settled_reward_pence IS NULL OR settled_reward_pence >= 0",
            name="ck_weeks_reward_not_negative",
        ),
        sa.CheckConstraint(
            "settled_total_pence IS NULL OR settled_total_pence >= 0",
            name="ck_weeks_total_not_negative",
        ),
        sa.CheckConstraint(
            "settled_total_pence IS NULL OR settled_total_pence ="
            " settled_base_pence + settled_chore_pay_pence"
            " + settled_bonus_pence + settled_reward_pence",
            name="ck_weeks_total_is_the_sum_of_its_parts",
        ),
        sa.CheckConstraint(
            "paid_at IS NULL OR status IN ('settled', 'voided')",
            name="ck_weeks_only_a_closed_week_is_paid",
        ),
        sa.CheckConstraint(
            "deposited_pence IS NULL OR deposited_pence >= 0",
            name="ck_weeks_deposit_not_negative",
        ),
        sa.CheckConstraint(
            "overridden_by IS NULL OR (status = 'settled'"
            " AND optimum_total_pence IS NOT NULL)",
            name="ck_weeks_an_override_is_recorded_in_full",
        ),
        sa.CheckConstraint(
            "override_reason IS NULL OR overridden_by IS NOT NULL",
            name="ck_weeks_only_an_override_has_a_reason",
        ),
        sa.CheckConstraint(
            "optimum_total_pence IS NULL OR optimum_total_pence >= 0",
            name="ck_weeks_optimum_not_negative",
        ),
        sa.CheckConstraint(
            "overridden_by IS NULL"
            " OR settled_total_pence >= optimum_total_pence"
            " OR (override_reason IS NOT NULL AND length(trim(override_reason)) > 0)",
            name="ck_weeks_an_override_that_costs_money_says_why",
        ),
    )




def upgrade() -> None:
    for name in WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    # SQLite cannot add a CHECK in place, so the table is rebuilt from the
    # definition above. The alter_column is a no-op that gives the batch
    # something to do, because an empty batch does not rebuild.
    with op.batch_alter_table(
        "weeks", schema=None, copy_from=_weeks_table(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("override_reason", existing_type=sa.Text())

    for statement in WEEKS_TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    # The constraint cannot be removed without rebuilding the table again, and
    # nothing stored under it becomes invalid without it. Left in place.
    pass
