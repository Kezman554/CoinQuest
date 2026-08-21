"""a chore may be due on chosen weekdays

A sixth cadence, WEEKDAYS, sits beside DAILY: it produces one instance for
each of the days the definition chooses, rather than every day. `weekdays`
holds the chosen days as WEEKDAY_TOKENS joined by commas, canonically
Monday-first (app.models.chores.parse_weekdays / format_weekdays) — required
for a weekdays chore and forbidden for every other cadence, mirroring
times_per_week's own CHECK exactly.

The CHECK is added by hand: Alembic does not compare CHECK constraints on
SQLite, so autogenerate only found the column.

Revision ID: 4872595d1036
Revises: 9dbe9580e290
Create Date: 2026-08-21 15:38:01.498167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = '4872595d1036'
down_revision: Union[str, None] = '9dbe9580e290'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('chore_definitions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('weekdays', sa.String(length=64), nullable=True))
        batch_op.create_check_constraint(
            'ck_chore_definitions_weekdays_only_for_weekdays_cadence',
            "(cadence = 'weekdays' AND weekdays IS NOT NULL)"
            " OR (cadence <> 'weekdays' AND weekdays IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table('chore_definitions', schema=None) as batch_op:
        batch_op.drop_constraint(
            'ck_chore_definitions_weekdays_only_for_weekdays_cadence', type_='check'
        )
        batch_op.drop_column('weekdays')
