"""Add analytics events table

Revision ID: add_analytics_events_table
Revises: 312620ebe819_add_scouting_team_number_to_relevant_
Create Date: 2025-09-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_analytics_events_table'
down_revision = '312620ebe819'
branch_labels = None
depends_on = None


def upgrade():
    # This migration was intentionally left empty as a placeholder.
    # If you want to add analytics tables, add the creation commands here.
    pass


def downgrade():
    # Reverse of upgrade (no-op for placeholder)
    pass
