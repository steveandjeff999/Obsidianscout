"""Merge multiple heads created during local edits

Revision ID: merge_heads_resolve_20250918
Revises: 8f0a126e6ef6, add_added_by_to_scouting_alliance_event, add_analytics_events_table, d4e8f7b9a1c2
Create Date: 2025-09-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'merge_heads_resolve_20250918'
down_revision = ('8f0a126e6ef6', 'add_added_by_to_scouting_alliance_event', 'add_analytics_events_table', 'd4e8f7b9a1c2')
branch_labels = None
depends_on = None


def upgrade():
    # Merge migration: no DB operations required - this file creates a single graph merge point
    pass


def downgrade():
    # Downgrade is a no-op for this merge migration
    pass
