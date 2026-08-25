"""a settled week may be reopened narrowly

"A settled week is a closed event" has held since the first migration, and
still does: nothing here lets a rule change reach backwards, and nothing
here lets a week settle itself twice by accident. What it did not allow for
is a parent's own mistake, made on purpose and later regretted — the wrong
figure agreed, a payment marked before it should have been. Until now there
was no way back from that short of editing the database by hand, which is
exactly the kind of "fix" this schema exists to make unnecessary.

Three things land together:

  week_reopenings — a new, append-only table. One row per reopening: who,
  when, why, and a full copy of the week's closing figures as they stood the
  moment before, since the week's own columns move on the instant the reopen
  closes. Reused the moment SettlementLine and ChoreInstance already
  established: a mistake is corrected by writing something new, never by
  editing what happened.

  The weeks trigger gains its one controlled exception. A reopen is defined
  structurally, by what it clears in the same UPDATE: a transition to `open`
  with every closing figure — the settled amounts, closed_at, and any
  override — set back to NULL in one statement. There is no other shape of
  change to a closed row's guarded columns this trigger permits; anything
  that reopens without clearing all of them, or clears them without actually
  reopening, still hits the abort exactly as it always has. The CHECK that
  already required an open week to carry no total now requires it to carry
  none of its parts either, which is what makes "cleared" checkable at the
  row level and not just a convention the trigger happens to trust.

  savings_ledger gains a second way a balance may fall: a reversal, for
  undoing a deposit that should not have counted — a reopened week's payment,
  unwound. Not a withdrawal: the child did not choose to take this out, and
  the two need to read differently a year later. Stored negative for the
  same reason a withdrawal is, and the CHECK now says so for both.

Revision ID: 6131c9c1284a
Revises: a4a5f729d606
Create Date: 2026-08-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = '6131c9c1284a'
down_revision: Union[str, None] = 'a4a5f729d606'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- The weeks triggers, before and after -----------------------------------
#
# Repeated in full rather than imported: a migration is a record of what was
# run, and must not change meaning later because another file did.

OLD_WEEKS_TRIGGERS = {
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

NEW_WEEKS_TRIGGERS = {
    "settled_week_figures_are_final": """
        CREATE TRIGGER settled_week_figures_are_final
        BEFORE UPDATE ON weeks
        FOR EACH ROW WHEN OLD.status IN ('settled', 'voided')
            AND NOT (
                -- The one controlled exception: reopening a closed week,
                -- authorised like any other write
                -- (app.services.settlement.reopen) and recorded in
                -- week_reopenings before this update ever runs. A reopen is
                -- defined by what it clears, in the same statement — there
                -- is no other way for a closed week's guarded columns to
                -- move.
                NEW.status = 'open'
                AND NEW.start_date IS OLD.start_date
                AND NEW.end_date IS OLD.end_date
                AND NEW.settled_base_pence IS NULL
                AND NEW.settled_chore_pay_pence IS NULL
                AND NEW.settled_bonus_pence IS NULL
                AND NEW.settled_reward_pence IS NULL
                AND NEW.settled_total_pence IS NULL
                AND NEW.closed_at IS NULL
                AND NEW.overridden_by IS NULL
                AND NEW.override_reason IS NULL
                AND NEW.optimum_total_pence IS NULL
            )
            AND (
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
    "a_closed_week_is_not_deleted": OLD_WEEKS_TRIGGERS["a_closed_week_is_not_deleted"],
}

SAVINGS_TRIGGERS = {
    "savings_are_not_updated": """
        CREATE TRIGGER savings_are_not_updated
        BEFORE UPDATE ON savings_ledger
        BEGIN
            SELECT RAISE(ABORT, 'the savings ledger is append-only');
        END
    """,
    "savings_are_not_deleted": """
        CREATE TRIGGER savings_are_not_deleted
        BEFORE DELETE ON savings_ledger
        BEGIN
            SELECT RAISE(ABORT, 'the savings ledger is append-only');
        END
    """,
}

WEEK_REOPENINGS_TRIGGERS = {
    "week_reopenings_are_not_updated": """
        CREATE TRIGGER week_reopenings_are_not_updated
        BEFORE UPDATE ON week_reopenings
        BEGIN
            SELECT RAISE(ABORT, 'a reopening is part of the record and is not edited');
        END
    """,
    "week_reopenings_are_not_deleted": """
        CREATE TRIGGER week_reopenings_are_not_deleted
        BEFORE DELETE ON week_reopenings
        BEGIN
            SELECT RAISE(ABORT, 'a reopening is part of the record and is not deleted');
        END
    """,
}


def _weeks_table():
    """The weeks table as this revision leaves it.

    Written out rather than imported from app.models: a migration that reads
    the live model rebuilds whatever the model happens to say today, which
    stops the revision running against an empty database the moment a later
    one adds a column. Identical to 3c1f6a2d9b74's shape except for the one
    CHECK tightened below: an open week now carries none of its parts, not
    only no total, which is what makes a reopen's "everything cleared"
    checkable at the row level.
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
            "   AND settled_base_pence IS NULL AND settled_chore_pay_pence IS NULL"
            "   AND settled_bonus_pence IS NULL AND settled_reward_pence IS NULL"
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


def _savings_ledger_table():
    """The savings ledger as this revision leaves it: unchanged in shape, one
    CHECK widened to admit the second kind of entry that may fall a balance.
    """
    return sa.Table(
        "savings_ledger",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("amount_pence", sa.Integer(), nullable=False),
        sa.Column("balance_after_pence", sa.Integer(), nullable=False),
        sa.Column("week_id", sa.Integer()),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_savings_ledger"),
        sa.ForeignKeyConstraint(
            ["week_id"], ["weeks.id"],
            name="fk_savings_ledger_week_id_weeks", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(entry_type IN ('withdrawal', 'reversal') AND amount_pence < 0)"
            " OR (entry_type NOT IN ('withdrawal', 'reversal') AND amount_pence >= 0)",
            name="ck_savings_ledger_a_withdrawal_or_reversal_is_negative",
        ),
        sa.CheckConstraint(
            "balance_after_pence >= 0", name="ck_savings_ledger_balance_not_negative"
        ),
    )


def upgrade() -> None:
    for name in OLD_WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for name in SAVINGS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    # SQLite cannot alter a CHECK in place; both tables are rebuilt from their
    # definitions above. Each alter_column is a no-op that gives its batch
    # something to do, because an empty batch does not rebuild.
    with op.batch_alter_table(
        "weeks", schema=None, copy_from=_weeks_table(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("settled_total_pence", existing_type=sa.Integer())

    with op.batch_alter_table(
        "savings_ledger", schema=None, copy_from=_savings_ledger_table(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("amount_pence", existing_type=sa.Integer())

    for statement in NEW_WEEKS_TRIGGERS.values():
        op.execute(statement)
    for statement in SAVINGS_TRIGGERS.values():
        op.execute(statement)

    op.create_table(
        "week_reopenings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("week_id", sa.Integer(), nullable=False),
        sa.Column("reopened_by", sa.String(length=60), nullable=False),
        sa.Column("reopened_at", app.models.base.UtcDateTime(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "previous_status",
            sa.Enum(
                "open", "settled", "voided",
                name="ck_weekstatus", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("previous_base_pence", sa.Integer(), nullable=False),
        sa.Column("previous_chore_pay_pence", sa.Integer(), nullable=False),
        sa.Column("previous_bonus_pence", sa.Integer(), nullable=False),
        sa.Column("previous_reward_pence", sa.Integer(), nullable=False),
        sa.Column("previous_total_pence", sa.Integer(), nullable=False),
        sa.Column("previous_closed_at", app.models.base.UtcDateTime(), nullable=False),
        sa.Column("previous_void_reason", sa.Text(), nullable=True),
        sa.Column("previous_overridden_by", sa.String(length=60), nullable=True),
        sa.Column("previous_override_reason", sa.Text(), nullable=True),
        sa.Column("was_paid", sa.Boolean(), nullable=False),
        sa.Column("previous_paid_at", app.models.base.UtcDateTime(), nullable=True),
        sa.Column("previous_deposited_pence", sa.Integer(), nullable=True),
        sa.Column("reversed_deposit_pence", sa.Integer(), nullable=False),
        sa.Column("reversal_entry_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name=op.f("ck_week_reopenings_a_reopen_states_its_reason")
        ),
        sa.CheckConstraint(
            "previous_status IN ('settled', 'voided')",
            name=op.f("ck_week_reopenings_only_a_closed_week_is_reopened"),
        ),
        sa.CheckConstraint(
            "previous_base_pence >= 0", name=op.f("ck_week_reopenings_previous_base_not_negative")
        ),
        sa.CheckConstraint(
            "previous_chore_pay_pence >= 0",
            name=op.f("ck_week_reopenings_previous_chore_pay_not_negative"),
        ),
        sa.CheckConstraint(
            "previous_bonus_pence >= 0",
            name=op.f("ck_week_reopenings_previous_bonus_not_negative"),
        ),
        sa.CheckConstraint(
            "previous_reward_pence >= 0",
            name=op.f("ck_week_reopenings_previous_reward_not_negative"),
        ),
        sa.CheckConstraint(
            "previous_total_pence >= 0",
            name=op.f("ck_week_reopenings_previous_total_not_negative"),
        ),
        sa.CheckConstraint(
            "previous_deposited_pence IS NULL OR previous_deposited_pence >= 0",
            name=op.f("ck_week_reopenings_previous_deposit_not_negative"),
        ),
        sa.CheckConstraint(
            "reversed_deposit_pence >= 0",
            name=op.f("ck_week_reopenings_reversed_deposit_not_negative"),
        ),
        sa.CheckConstraint(
            "was_paid = 1 OR reversed_deposit_pence = 0",
            name=op.f("ck_week_reopenings_only_a_paid_week_reverses_a_deposit"),
        ),
        sa.ForeignKeyConstraint(
            ["week_id"], ["weeks.id"],
            name=op.f("fk_week_reopenings_week_id_weeks"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_entry_id"], ["savings_ledger.id"],
            name=op.f("fk_week_reopenings_reversal_entry_id_savings_ledger"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_week_reopenings")),
    )
    with op.batch_alter_table("week_reopenings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_week_reopenings_week_id"), ["week_id"], unique=False
        )

    for statement in WEEK_REOPENINGS_TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in WEEK_REOPENINGS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("week_reopenings")

    for name in NEW_WEEKS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for statement in OLD_WEEKS_TRIGGERS.values():
        op.execute(statement)

    # The widened savings_ledger CHECK and the tightened weeks CHECK are both
    # left in place: neither can be reverted without another rebuild, and
    # nothing stored under either becomes invalid without it — the same
    # judgement 3c1f6a2d9b74 and 9040ce063e24 made for the same reason.
