"""standalone savings deposits

A second route into the savings ledger, independent of payday — real-world
money (birthday, a gift, the opening balance at go-live) arriving outside
the cash/bank split at settlement.

savings_ledger gains posted_by: who a standalone deposit was posted by,
null for every other kind of entry including a payday-split deposit, which
belongs to the week it split from rather than to a person. A plain string,
not an enum — the fixed list of names it may hold (app.config.parent_names,
plus the child) is deliberately config, not schema, so a third person is an
env change, not a migration. SQLite cannot add a CHECK in place, so the
table is rebuilt from _savings_ledger_table() below, and — because it
carries the two triggers that make it append-only — those triggers are
dropped first and recreated after, the same shape 6131c9c1284a already
used for this exact table.

savings_deposit_requests is new, and unlike the two ledgers it is not
append-only: it is Oliver's own proposal, sitting pending until a parent
confirms it (writing the real SavingsEntry and linking back via
savings_entry_id) or rejects it (never touching the ledger at all) — the
same claimed/confirmed shape chore_instances already is, not the shape
either ledger is. A plain create_table, with no triggers to preserve.

`alembic check` also flags a pre-existing, unrelated drift on
savings_month_matches: its unique constraint is named
uq_savings_month_matches_period_start here, one_settlement_per_month in
the model. Left alone rather than folded in — that table carries the
append-only triggers a settled month's own immutability depends on, and
renaming its constraint means rebuilding it (SQLite cannot rename one in
place), which means dropping and recreating those triggers around the
rebuild too. That is real, separate surgery this card has no reason to
risk; see docs/progress.txt for the note.

Revision ID: 8a5d83828968
Revises: 7b10cc8d801f
Create Date: 2026-09-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = '8a5d83828968'
down_revision: Union[str, None] = '7b10cc8d801f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _savings_ledger_table():
    """The savings ledger's shape immediately before this revision — what a
    batch rebuild copies its data *from*, so it has to match what is
    actually in the database when each direction runs, not what either end
    of this migration leaves behind.

    Written out rather than read from app.models: a migration that reads the
    live model rebuilds whatever the model happens to say today, which stops
    this revision running correctly once a later one changes the table
    again. Copied from 6131c9c1284a's own version of this same helper.
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
    for name in SAVINGS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table(
        "savings_ledger", schema=None,
        copy_from=_savings_ledger_table(), recreate="always",
    ) as batch_op:
        batch_op.add_column(sa.Column("posted_by", sa.String(length=60)))
        batch_op.create_check_constraint(
            "only_a_deposit_names_who_posted_it",
            "posted_by IS NULL OR entry_type = 'deposit'",
        )

    for statement in SAVINGS_TRIGGERS.values():
        op.execute(statement)

    op.create_table(
        'savings_deposit_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('amount_pence', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('posted_by', sa.String(length=60), nullable=False),
        sa.Column('occurred_on', sa.Date(), nullable=False),
        sa.Column(
            'state',
            sa.Enum(
                'pending', 'confirmed', 'rejected',
                name='ck_depositrequeststate', native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column('submitted_at', app.models.base.UtcDateTime(), nullable=False),
        sa.Column('decided_at', app.models.base.UtcDateTime(), nullable=True),
        sa.Column('decided_by', sa.String(length=60), nullable=True),
        sa.Column('savings_entry_id', sa.Integer(), nullable=True),
        sa.CheckConstraint('amount_pence > 0', name=op.f('ck_savings_deposit_requests_amount_positive')),
        sa.CheckConstraint(
            "length(trim(note)) > 0",
            name=op.f('ck_savings_deposit_requests_a_deposit_states_its_note'),
        ),
        sa.CheckConstraint(
            "(state = 'pending') = (decided_at IS NULL AND decided_by IS NULL)",
            name=op.f('ck_savings_deposit_requests_a_decision_carries_its_own_timestamp_and_author'),
        ),
        sa.CheckConstraint(
            "(state = 'confirmed') = (savings_entry_id IS NOT NULL)",
            name=op.f('ck_savings_deposit_requests_only_a_confirmation_names_its_ledger_entry'),
        ),
        sa.ForeignKeyConstraint(
            ['savings_entry_id'], ['savings_ledger.id'],
            name=op.f('fk_savings_deposit_requests_savings_entry_id_savings_ledger'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_savings_deposit_requests')),
    )


def downgrade() -> None:
    op.drop_table('savings_deposit_requests')

    for name in SAVINGS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")

    # copy_from is this revision's *upgrade* target — posted_by and its CHECK
    # both exist in the real table at this point, which is what a batch
    # rebuild needs to see to copy the data out before they are dropped.
    before = _savings_ledger_table()
    before.append_column(sa.Column("posted_by", sa.String(length=60)))
    before.append_constraint(
        sa.CheckConstraint(
            "posted_by IS NULL OR entry_type = 'deposit'",
            name="ck_savings_ledger_only_a_deposit_names_who_posted_it",
        )
    )

    with op.batch_alter_table(
        "savings_ledger", schema=None, copy_from=before, recreate="always",
    ) as batch_op:
        batch_op.drop_constraint("only_a_deposit_names_who_posted_it", type_="check")
        batch_op.drop_column("posted_by")

    for statement in SAVINGS_TRIGGERS.values():
        op.execute(statement)
