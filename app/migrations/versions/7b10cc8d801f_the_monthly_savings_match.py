"""the monthly savings match

Two things land together, closing the gap app/routers/weeks.py has named
since Session H: nothing computed a match from the savings ledger.

  scheme_settings gains three figures — where the match ladder starts, where
  it stops, and the cap on the portion of a balance it matches — reviewable
  by a parent the same way the weekly basic pay already is. Seeded to 5%,
  10% and £100 so an existing household's ladder starts exactly where the
  scheme's own rules say it should.

  savings_month_matches is a new, append-only table: one row per calendar
  month, ever, storing the figures that month's match actually paid on —
  never a pointer back to scheme_settings, for the same reason `weeks` stores
  its own settled figures rather than rereading a chore definition. Its own
  CHECK reproduces the match arithmetic, so a row that disagrees with its own
  formula is refused by the database, not only by whatever service wrote it.

Revision ID: 7b10cc8d801f
Revises: c3f8b21a7d40
Create Date: 2026-09-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = '7b10cc8d801f'
down_revision: Union[str, None] = 'c3f8b21a7d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TRIGGERS = {
    "savings_month_matches_are_not_updated": """
        CREATE TRIGGER savings_month_matches_are_not_updated
        BEFORE UPDATE ON savings_month_matches
        BEGIN
            SELECT RAISE(ABORT, 'a settled month is closed forever; it is not edited');
        END
    """,
    "savings_month_matches_are_not_deleted": """
        CREATE TRIGGER savings_month_matches_are_not_deleted
        BEFORE DELETE ON savings_month_matches
        BEGIN
            SELECT RAISE(ABORT, 'a settled month is closed forever; it is not deleted');
        END
    """,
}


def upgrade() -> None:
    with op.batch_alter_table('scheme_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'savings_match_start_rate_percent', sa.Integer(),
                nullable=False, server_default='5',
            )
        )
        batch_op.add_column(
            sa.Column(
                'savings_match_ceiling_rate_percent', sa.Integer(),
                nullable=False, server_default='10',
            )
        )
        batch_op.add_column(
            sa.Column(
                'savings_match_cap_pence', sa.Integer(),
                nullable=False, server_default='10000',
            )
        )
        batch_op.create_check_constraint(
            'ck_scheme_settings_savings_match_start_rate_within_range',
            'savings_match_start_rate_percent >= 0'
            ' AND savings_match_start_rate_percent <= savings_match_ceiling_rate_percent',
        )
        batch_op.create_check_constraint(
            'ck_scheme_settings_savings_match_ceiling_rate_at_most_100',
            'savings_match_ceiling_rate_percent <= 100',
        )
        batch_op.create_check_constraint(
            'ck_scheme_settings_savings_match_cap_not_negative',
            'savings_match_cap_pence >= 0',
        )

    op.create_table(
        'savings_month_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('balance_low_pence', sa.Integer(), nullable=False),
        sa.Column('had_withdrawal', sa.Boolean(), nullable=False),
        sa.Column('rate_percent', sa.Integer(), nullable=False),
        sa.Column('cap_pence', sa.Integer(), nullable=False),
        sa.Column('match_pence', sa.Integer(), nullable=False),
        sa.Column('match_entry_id', sa.Integer(), nullable=True),
        sa.Column('settled_by', sa.String(length=60), nullable=False),
        sa.Column('settled_at', app.models.base.UtcDateTime(), nullable=False),
        sa.Column('created_at', app.models.base.UtcDateTime(), nullable=False),
        sa.CheckConstraint(
            "strftime('%d', period_start) = '01'",
            name=op.f('ck_savings_month_matches_period_start_is_the_first_of_the_month'),
        ),
        sa.CheckConstraint(
            "date(period_end, '+1 day') = date(period_start, '+1 month')",
            name=op.f('ck_savings_month_matches_period_end_is_the_last_of_the_same_month'),
        ),
        sa.CheckConstraint(
            'balance_low_pence >= 0',
            name=op.f('ck_savings_month_matches_balance_low_not_negative'),
        ),
        sa.CheckConstraint(
            'rate_percent >= 0 AND rate_percent <= 100',
            name=op.f('ck_savings_month_matches_rate_between_0_and_100'),
        ),
        sa.CheckConstraint(
            'cap_pence >= 0', name=op.f('ck_savings_month_matches_cap_not_negative')
        ),
        sa.CheckConstraint(
            'match_pence >= 0', name=op.f('ck_savings_month_matches_match_not_negative')
        ),
        sa.CheckConstraint(
            'match_pence = (MIN(balance_low_pence, cap_pence) * rate_percent + 50) / 100',
            name=op.f('ck_savings_month_matches_match_is_the_rate_applied_to_the_capped_low'),
        ),
        sa.ForeignKeyConstraint(
            ['match_entry_id'], ['savings_ledger.id'],
            name=op.f('fk_savings_month_matches_match_entry_id_savings_ledger'),
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_savings_month_matches')),
        sa.UniqueConstraint(
            'period_start', name=op.f('uq_savings_month_matches_period_start')
        ),
    )

    for statement in TRIGGERS.values():
        op.execute(statement)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table('savings_month_matches')

    with op.batch_alter_table('scheme_settings', schema=None) as batch_op:
        batch_op.drop_constraint(
            'ck_scheme_settings_savings_match_cap_not_negative', type_='check'
        )
        batch_op.drop_constraint(
            'ck_scheme_settings_savings_match_ceiling_rate_at_most_100', type_='check'
        )
        batch_op.drop_constraint(
            'ck_scheme_settings_savings_match_start_rate_within_range', type_='check'
        )
        batch_op.drop_column('savings_match_cap_pence')
        batch_op.drop_column('savings_match_ceiling_rate_percent')
        batch_op.drop_column('savings_match_start_rate_percent')
