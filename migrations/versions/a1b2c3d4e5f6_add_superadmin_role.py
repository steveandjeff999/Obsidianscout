"""add superadmin role

Revision ID: a1b2c3d4e5f6
Revises: 312620ebe819
Create Date: 2025-07-30 18:42:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '312620ebe819'
branch_labels = None
depends_on = None


def upgrade():
    op.bulk_insert(
        sa.table('role',
            sa.column('name', sa.String),
            sa.column('description', sa.String)
        ),
        [
            {'name': 'superadmin', 'description': 'User with access to all teams and administrative functions.'}
        ]
    )


def downgrade():
    op.execute("DELETE FROM role WHERE name = 'superadmin'")
