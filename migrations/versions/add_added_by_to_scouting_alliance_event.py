"""Add added_by column to scouting_alliance_event

Revision ID: add_added_by_to_scouting_alliance_event
Revises: 0aeb425f2f02
Create Date: 2025-09-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_added_by_to_scouting_alliance_event'
down_revision = '0aeb425f2f02'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    table_exists = 'scouting_alliance_event' in insp.get_table_names()
    cols = [c['name'] for c in insp.get_columns('scouting_alliance_event')] if table_exists else []
    if table_exists and 'added_by' not in cols:
        with op.batch_alter_table('scouting_alliance_event', schema=None) as batch_op:
            batch_op.add_column(sa.Column('added_by', sa.Integer(), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    table_exists = 'scouting_alliance_event' in insp.get_table_names()
    cols = [c['name'] for c in insp.get_columns('scouting_alliance_event')] if table_exists else []
    if table_exists and 'added_by' in cols:
        with op.batch_alter_table('scouting_alliance_event', schema=None) as batch_op:
            batch_op.drop_column('added_by')
