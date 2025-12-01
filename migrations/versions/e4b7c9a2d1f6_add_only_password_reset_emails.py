"""Add only_password_reset_emails to user

Revision ID: e4b7c9a2d1f6
Revises: merge_heads_resolve_20250918
Create Date: 2025-11-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4b7c9a2d1f6'
down_revision = 'merge_heads_resolve_20250918'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'user' in existing_tables:
        cols = [c['name'] for c in inspector.get_columns('user')]
        if 'only_password_reset_emails' not in cols:
            with op.batch_alter_table('user', schema=None) as batch_op:
                batch_op.add_column(sa.Column('only_password_reset_emails', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'user' in existing_tables:
        cols = [c['name'] for c in inspector.get_columns('user')]
        if 'only_password_reset_emails' in cols:
            with op.batch_alter_table('user', schema=None) as batch_op:
                batch_op.drop_column('only_password_reset_emails')
