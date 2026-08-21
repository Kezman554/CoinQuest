"""administered chores are marked, not claimed

Some bonus chores are not the child's to claim at all — the clock test needs
Nick to give it and judge it, so the "done" has to come from a parent
directly rather than waiting on a claim nobody is going to make. This column
records that fact about a definition. It changes no behaviour by itself: the
claim endpoint does not read it yet, so today it is documentation the parent
screen can show and filter on, nothing more.

Defaulted to false (server_default, since chore_definitions already has rows)
so every existing chore stays exactly what it always was — claimed by the
child — until someone deliberately marks one administered.

Revision ID: 9dbe9580e290
Revises: 3c1f6a2d9b74
Create Date: 2026-08-21 15:07:51.293957

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = '9dbe9580e290'
down_revision: Union[str, None] = '3c1f6a2d9b74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('chore_definitions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_administered', sa.Boolean(), server_default='0', nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('chore_definitions', schema=None) as batch_op:
        batch_op.drop_column('is_administered')
