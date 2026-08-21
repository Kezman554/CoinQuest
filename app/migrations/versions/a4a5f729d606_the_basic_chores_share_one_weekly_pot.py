"""the basic chores share one weekly pot

Entering £2 on "Make bed" and another £2 on "Lunchbox and cups" summed to £4
of chore pay, which is not what pocket-money-rules.md §2 describes: a single
£2 pot that the basic chores collectively gate, not one they each carry a
slice of. scheme_settings holds that figure now — one row, seeded to 200
(today's £2) so an existing household's basic chore pay is unchanged the
moment this ships. Individual BASIC chores keep their amount_pence column
(nothing here touches ChoreDefinition), but recovery.py stops reading it for
that category — see WeekAssessment.chore_pay_at_stake_pence.

Revision ID: a4a5f729d606
Revises: 4872595d1036
Create Date: 2026-08-21 16:19:37.134877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = 'a4a5f729d606'
down_revision: Union[str, None] = '4872595d1036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scheme_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('weekly_basic_pay_pence', sa.Integer(), nullable=False),
    sa.Column('updated_at', app.models.base.UtcDateTime(), nullable=False),
    sa.CheckConstraint('weekly_basic_pay_pence >= 0', name=op.f('ck_scheme_settings_weekly_basic_pay_not_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scheme_settings'))
    )

    # The one row. Every reader assumes it exists; nothing ever inserts a
    # second. updated_at is set explicitly rather than left to a Python-side
    # default, since this INSERT runs as raw SQL, not through the model.
    op.execute(
        "INSERT INTO scheme_settings (id, weekly_basic_pay_pence, updated_at)"
        " VALUES (1, 200, CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_table('scheme_settings')
