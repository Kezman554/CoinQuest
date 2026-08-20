"""record an overridden settlement

Settlement proposes and a parent agrees. Sometimes they agree to something
other than what was proposed: a make-good that costs more than the chore pay
it rescues is declined by the optimiser, and a passed week can still be worth
more to a child than the fifty pence it cost.

A week settled that way has to say so. Without these columns it would read, a
year later, as a week where the app got its sums wrong — and the figure it
turned down is as much a part of the record as the one it paid, because the
difference between them is the whole story.

The two triggers on `weeks` are dropped and recreated around the rebuild, and
the immutability trigger now covers the new columns: an override is part of
the closing figures and is frozen with them.

Revision ID: 1eb8e8b3e4ae
Revises: 9040ce063e24
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models

# revision identifiers, used by Alembic.
revision: str = '1eb8e8b3e4ae'
down_revision: Union[str, None] = '9040ce063e24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Repeated rather than imported: a migration is a record of what was run, and
# must not change meaning later because another file did.
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
    )


def upgrade() -> None:
    for name in WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table("weeks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("overridden_by", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("override_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("optimum_total_pence", sa.Integer(), nullable=True))

    # SQLite cannot add a CHECK in place, so the table is rebuilt from the
    # model. The alter_column is a no-op that gives the batch something to do,
    # because an empty batch does not rebuild.
    with op.batch_alter_table(
        "weeks", schema=None, copy_from=_weeks_table(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("optimum_total_pence", existing_type=sa.Integer())

    for statement in WEEKS_TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table("weeks", schema=None) as batch_op:
        batch_op.drop_column("optimum_total_pence")
        batch_op.drop_column("override_reason")
        batch_op.drop_column("overridden_by")
