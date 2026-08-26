"""a marked miss no longer names a parent

Marking a chore missed stopped carrying the PIN (Session Y — see
app/routers/claims.py, which states the rule it reverses and why). The check
that came in with 82826e03b64d — "miss_origin <> 'parent_marked' OR
authorised_by IS NOT NULL" — was the schema's way of saying that a decision
names whoever made it, and it was right while marking a miss was a decision
somebody had to prove themselves to make. It is now a proposal that pays
nothing, made by whoever is standing at the wall screen, and there is no
credential behind it to name. Filling the column in anyway would put a
parent's name against something no parent authorised, which is the exact
untruth the sibling check (an inferred miss has no author) exists to prevent.

What survives, unchanged:

  - `an_inferred_miss_has_no_author`. Settlement still authorises nothing.
  - `a_confirmation_names_its_author`. Confirming is money and still carries
    the PIN.
  - `a_miss_says_how_it_arose`, and MissOrigin itself. PARENT_MARKED still
    means what it always meant — a miss decided while the week was open, as
    against one inferred from silence after it closed — and that distinction
    is what `Miss.is_definite`, the recovery window, and the new clear-a-miss
    endpoint all still turn on. Only the "names the parent" half is gone.

Rebuilt with an explicit `copy_from` rather than by reflecting the live
table. SQLite cannot drop a CHECK, so the table has to be recreated either
way, and reflecting it would recreate every other constraint through the
metadata naming convention a second time — which is how the existing names
came to read ck_chore_instances_ck_chore_instances_… Spelling the table out
here keeps every remaining name byte-for-byte what it already is in the real
database, and this migration is the one place that has to know them.

Revision ID: c3f8b21a7d40
Revises: 6131c9c1284a
Create Date: 2026-08-26 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models.base  # custom column types used by the models


# revision identifiers, used by Alembic.
revision: str = 'c3f8b21a7d40'
down_revision: Union[str, None] = '6131c9c1284a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: The name as the real database holds it, for the table spelled out below.
NAMES_THE_PARENT = (
    'ck_chore_instances_ck_chore_instances_a_parent_marked_miss_names_the_parent'
)

#: The same constraint, as it has to be *asked for*. Every op here goes
#: through the metadata's naming convention (ck_%(table_name)s_%(constraint
#: _name)s), which prefixes whatever it is given — which is precisely how the
#: stored name came to carry the prefix twice. Handing it the once-prefixed
#: name yields the name above. It is checked: a mismatch fails the migration
#: with "No such constraint" rather than silently rebuilding the table with
#: the check still on it.
NAMES_THE_PARENT_AS_ASKED = (
    'ck_chore_instances_a_parent_marked_miss_names_the_parent'
)


def _table(*, names_the_parent: bool) -> sa.Table:
    """chore_instances as it stands, with that one CHECK in or out.

    A bare MetaData with no naming convention on purpose: every name below is
    given literally, exactly as the real database already holds it.
    """
    constraints = [
        sa.PrimaryKeyConstraint('id', name='pk_chore_instances'),
        sa.ForeignKeyConstraint(
            ['definition_id'], ['chore_definitions.id'],
            name='fk_chore_instances_definition_id_chore_definitions',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['week_id'], ['weeks.id'],
            name='fk_chore_instances_week_id_weeks',
            ondelete='RESTRICT',
        ),
        sa.ForeignKeyConstraint(
            ['recovered_instance_id'], ['chore_instances.id'],
            name='fk_chore_instances_recovered_instance_id_chore_instances',
            ondelete='SET NULL',
        ),
        sa.CheckConstraint(
            'quantity > 0', name='ck_chore_instances_quantity_positive'
        ),
        # No `sequence > 0` check: the model carries one, the real table has
        # never had it (b743007f1216 added the column without it), and this
        # migration's job is to reproduce what is actually there rather than
        # to quietly close an unrelated gap during a table rebuild.
        sa.CheckConstraint(
            'rejection_count >= 0',
            name='ck_chore_instances_ck_chore_instances_rejection_count_not_negative',
        ),
        sa.CheckConstraint(
            "(state = 'missed') = (miss_origin IS NOT NULL)",
            name='ck_chore_instances_ck_chore_instances_a_miss_says_how_it_arose',
        ),
        sa.CheckConstraint(
            "miss_origin <> 'inferred_at_settlement' OR authorised_by IS NULL",
            name=(
                'ck_chore_instances_ck_chore_instances'
                '_an_inferred_miss_has_no_author'
            ),
        ),
        sa.CheckConstraint(
            '(rejection_count = 0 AND rejected_at IS NULL)'
            ' OR (rejection_count > 0 AND rejected_at IS NOT NULL)',
            name=(
                'ck_chore_instances_ck_chore_instances'
                '_a_rejection_records_when_it_happened'
            ),
        ),
        sa.CheckConstraint(
            "state <> 'confirmed' OR authorised_by IS NOT NULL",
            name=(
                'ck_chore_instances_ck_chore_instances'
                '_a_confirmation_names_its_author'
            ),
        ),
        sa.CheckConstraint(
            "(state = 'claimed' AND claimed_at IS NOT NULL)"
            " OR (state = 'confirmed' AND confirmed_at IS NOT NULL)"
            " OR (state = 'missed' AND missed_at IS NOT NULL)"
            " OR state = 'untouched'",
            name='ck_chore_instances_state_carries_its_timestamp',
        ),
        sa.CheckConstraint(
            'recovered_instance_id IS NULL OR recovered_instance_id <> id',
            name='ck_chore_instances_an_instance_cannot_recover_itself',
        ),
    ]
    if names_the_parent:
        constraints.append(
            sa.CheckConstraint(
                "miss_origin <> 'parent_marked' OR authorised_by IS NOT NULL",
                name=NAMES_THE_PARENT,
            )
        )

    # Named, so the two partial indexes below can point at it. Both are
    # unique-per-slot rules the app relies on to stop a chore being generated
    # twice, and a rebuild that reproduced every constraint but silently
    # dropped them would be the worst kind of correct.
    due_date = sa.Column('due_date', sa.Date(), nullable=True)

    return sa.Table(
        'chore_instances',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('definition_id', sa.Integer(), nullable=False),
        sa.Column('week_id', sa.Integer(), nullable=False),
        due_date,
        sa.Column(
            'state',
            sa.Enum(
                'untouched', 'claimed', 'confirmed', 'missed',
                name='ck_instancestate', native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('claimed_at', app.models.base.UtcDateTime(), nullable=True),
        sa.Column('confirmed_at', app.models.base.UtcDateTime(), nullable=True),
        sa.Column('missed_at', app.models.base.UtcDateTime(), nullable=True),
        sa.Column('recovered_instance_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', app.models.base.UtcDateTime(), nullable=False),
        sa.Column(
            'sequence', sa.Integer(), server_default='1', nullable=False
        ),
        sa.Column('authorised_by', sa.String(length=60), nullable=True),
        sa.Column('rejected_at', app.models.base.UtcDateTime(), nullable=True),
        sa.Column(
            'rejection_count', sa.Integer(), server_default='0', nullable=False
        ),
        sa.Column(
            'miss_origin',
            sa.Enum(
                'parent_marked', 'inferred_at_settlement',
                name='ck_missorigin', native_enum=False, length=32,
            ),
            nullable=True,
        ),
        *constraints,
        sa.Index(
            'uq_chore_instances_definition_day',
            'definition_id',
            'due_date',
            unique=True,
            sqlite_where=due_date.isnot(None),
        ),
        sa.Index(
            'uq_chore_instances_definition_week_sequence',
            'definition_id',
            'week_id',
            'sequence',
            unique=True,
            sqlite_where=due_date.is_(None),
        ),
    )


def upgrade() -> None:
    with op.batch_alter_table(
        'chore_instances',
        copy_from=_table(names_the_parent=True),
        recreate='always',
    ) as batch_op:
        batch_op.drop_constraint(NAMES_THE_PARENT_AS_ASKED, type_='check')


def downgrade() -> None:
    """Put the check back.

    Any parent-marked miss recorded without an author while it was gone would
    fail it, which is correct: the rows and the constraint genuinely disagree,
    and silently rewriting somebody's name into them to make the DDL apply is
    the one thing this must not do.
    """
    with op.batch_alter_table(
        'chore_instances',
        copy_from=_table(names_the_parent=False),
        recreate='always',
    ) as batch_op:
        batch_op.create_check_constraint(
            NAMES_THE_PARENT_AS_ASKED,
            "miss_origin <> 'parent_marked' OR authorised_by IS NOT NULL",
        )
