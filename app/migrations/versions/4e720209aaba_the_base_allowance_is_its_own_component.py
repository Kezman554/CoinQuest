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


# The same two triggers as 82826e03b64d left them — which is to say as the
# initial schema wrote them, since nothing between the two touches `weeks`.
# They name settled_basic_pence, the column downgrade() renames back to.
# Repeated rather than imported, for the reason given on _weeks_table().
PRIOR_WEEKS_TRIGGERS = {
    "settled_week_figures_are_final": """
        CREATE TRIGGER settled_week_figures_are_final
        BEFORE UPDATE ON weeks
        FOR EACH ROW WHEN OLD.status IN ('settled', 'voided') AND (
               NEW.status               IS NOT OLD.status
            OR NEW.start_date           IS NOT OLD.start_date
            OR NEW.end_date             IS NOT OLD.end_date
            OR NEW.settled_basic_pence  IS NOT OLD.settled_basic_pence
            OR NEW.settled_bonus_pence  IS NOT OLD.settled_bonus_pence
            OR NEW.settled_reward_pence IS NOT OLD.settled_reward_pence
            OR NEW.settled_total_pence  IS NOT OLD.settled_total_pence
            OR NEW.closed_at            IS NOT OLD.closed_at
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


# The CHECKs this revision's rebuild leaves on `weeks` that name either the new
# column or the renamed one. Dropping a column does not drop the constraints
# that mention it, and a CHECK naming a column the same rebuild removed is what
# SQLite refuses — so these come off explicitly, by name.
BASE_ALLOWANCE_CONSTRAINTS = (
    "ck_weeks_closed_weeks_carry_their_figures",
    "ck_weeks_a_voided_week_loses_base_chore_pay_and_bonuses",
    "ck_weeks_base_not_negative",
    "ck_weeks_chore_pay_not_negative",
    "ck_weeks_total_is_the_sum_of_its_parts",
)


# And the ones 82826e03b64d had in their place, written against
# settled_basic_pence, for downgrade() to put back in the same rebuild.
PRIOR_WEEKS_CONSTRAINTS = {
    "ck_weeks_closed_weeks_carry_their_figures": (
        "(status = 'open'"
        "   AND settled_total_pence IS NULL AND closed_at IS NULL)"
        " OR (status IN ('settled', 'voided')"
        "   AND settled_basic_pence IS NOT NULL"
        "   AND settled_bonus_pence IS NOT NULL"
        "   AND settled_reward_pence IS NOT NULL"
        "   AND settled_total_pence IS NOT NULL"
        "   AND closed_at IS NOT NULL)"
    ),
    # Restored as it was, not as this revision would prefer it. It is the
    # constraint this revision exists to relax: it demands a voided week pay
    # nothing at all, and a voided week's rewards are legitimate now. If real
    # data disagrees with it the downgrade aborts here, loudly, and that is
    # correct — quietly zeroing somebody's rewards to make the DDL apply is the
    # one thing it must not do. Same judgement as c3f8b21a7d40's downgrade.
    "ck_weeks_a_voided_week_pays_nothing": "status <> 'voided' OR settled_total_pence = 0",
    "ck_weeks_basic_not_negative": "settled_basic_pence IS NULL OR settled_basic_pence >= 0",
    "ck_weeks_total_is_the_sum_of_its_parts": (
        "settled_total_pence IS NULL OR settled_total_pence ="
        " settled_basic_pence + settled_bonus_pence + settled_reward_pence"
    ),
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

    # copy_from and recreate="always" for the same reason upgrade() uses them,
    # and for one more: without a target shape Alembic reflects the live table
    # and carries every CHECK's raw SQL into the rebuild, including the ones
    # naming the column this rebuild drops. SQLite then refuses with `no such
    # column: settled_base_pence`, and the downgrade dies with the triggers
    # already gone.
    #
    # One rebuild does the whole reversal, which is why the rename happens
    # inside the batch here and outside it in upgrade(): the restored CHECKs
    # below name settled_basic_pence, so the column has to be called that by
    # the time the replacement table is written.
    with op.batch_alter_table(
        "weeks", schema=None, copy_from=_weeks_table(), recreate="always"
    ) as batch_op:
        for name in BASE_ALLOWANCE_CONSTRAINTS:
            batch_op.drop_constraint(op.f(name), type_="check")
        batch_op.drop_column("settled_base_pence")
        batch_op.alter_column(
            "settled_chore_pay_pence",
            new_column_name="settled_basic_pence",
            existing_type=sa.Integer(),
        )
        for name, sqltext in PRIOR_WEEKS_CONSTRAINTS.items():
            batch_op.create_check_constraint(op.f(name), sqltext)

    # The triggers as 82826e03b64d left them. Nothing below this revision puts
    # them back — 82826e03b64d does not touch `weeks` at all — so if they are
    # not restored here they are not restored anywhere, and a database that had
    # merely stepped back one revision would sit there with a settled week's
    # figures editable and a closed week deletable. A downgrade that refuses to
    # run is recoverable; one that silently disarms the append-only guarantee
    # the whole ledger rests on is not.
    for statement in PRIOR_WEEKS_TRIGGERS.values():
        op.execute(statement)


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
            "deposited_pence IS NULL"
            " OR (deposited_pence >= 0 AND deposited_pence <= settled_total_pence)",
            name="ck_weeks_deposit_within_the_payment",
        ),
    )
