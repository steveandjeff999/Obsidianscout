"""add custom_page table

Revision ID: 9f3b4c6d7e8f
Revises: 70930d576515
Create Date: 2025-09-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3b4c6d7e8f'
down_revision = '70930d576515'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'custom_page' not in insp.get_table_names():
        op.create_table(
        'custom_page',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('owner_team', sa.Integer(), nullable=False),
        sa.Column('owner_user', sa.String(length=80), nullable=False),
        sa.Column('widgets_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('1')),
    )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'custom_page' in insp.get_table_names():
        op.drop_table('custom_page')
