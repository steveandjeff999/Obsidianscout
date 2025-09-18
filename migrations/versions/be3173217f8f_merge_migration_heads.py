"""Merge migration heads

Revision ID: be3173217f8f
Revises: 0aeb425f2f02, 70930d576515, 123456789abc
Create Date: 2025-08-03 17:24:02.042911

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'be3173217f8f'
# Removed a non-existent down_revision '123456789abc' to fix migration graph
down_revision = ('0aeb425f2f02', '70930d576515')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
