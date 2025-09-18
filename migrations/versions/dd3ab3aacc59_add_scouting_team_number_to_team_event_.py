"""Add scouting_team_number to Team, Event, and Match models for full multi-tenancy

Revision ID: dd3ab3aacc59
Revises: a1b2c3d4e5f6
Create Date: 2025-08-01 08:24:37.739607

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dd3ab3aacc59'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Defensive/Idempotent migration: only add columns or drop constraints if they don't/do exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # event table
    event_cols = [c['name'] for c in inspector.get_columns('event')] if 'event' in inspector.get_table_names() else []
    event_uqs = [u.get('name') for u in inspector.get_unique_constraints('event')] if 'event' in inspector.get_table_names() else []
    with op.batch_alter_table('event', schema=None) as batch_op:
        if 'scouting_team_number' not in event_cols:
            batch_op.add_column(sa.Column('scouting_team_number', sa.Integer(), nullable=True))
        # Remove the unique constraint on code since multiple teams can have same event code
        if 'uq_event_code' in (event_uqs or []):
            try:
                batch_op.drop_constraint('uq_event_code', type_='unique')
            except Exception:
                # If drop fails for any reason (SQLite naming differences), ignore and continue
                pass

    # match table
    match_cols = [c['name'] for c in inspector.get_columns('match')] if 'match' in inspector.get_table_names() else []
    with op.batch_alter_table('match', schema=None) as batch_op:
        if 'scouting_team_number' not in match_cols:
            batch_op.add_column(sa.Column('scouting_team_number', sa.Integer(), nullable=True))

    # team table
    team_cols = [c['name'] for c in inspector.get_columns('team')] if 'team' in inspector.get_table_names() else []
    team_uqs = [u.get('name') for u in inspector.get_unique_constraints('team')] if 'team' in inspector.get_table_names() else []
    with op.batch_alter_table('team', schema=None) as batch_op:
        if 'scouting_team_number' not in team_cols:
            batch_op.add_column(sa.Column('scouting_team_number', sa.Integer(), nullable=True))
        # Remove the unique constraint on team_number since multiple scouting teams can have same team numbers
        if 'uq_team_team_number' in (team_uqs or []):
            try:
                batch_op.drop_constraint('uq_team_team_number', type_='unique')
            except Exception:
                pass
    # ### end Alembic commands ###


def downgrade():
    # Defensive downgrade: only recreate constraints/columns if appropriate
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'team' in inspector.get_table_names():
        team_cols = [c['name'] for c in inspector.get_columns('team')]
        with op.batch_alter_table('team', schema=None) as batch_op:
            if 'team_number' in team_cols:
                # recreate unique constraint if missing
                try:
                    batch_op.create_unique_constraint('uq_team_team_number', ['team_number'])
                except Exception:
                    pass
            if 'scouting_team_number' in team_cols:
                batch_op.drop_column('scouting_team_number')

    if 'match' in inspector.get_table_names():
        match_cols = [c['name'] for c in inspector.get_columns('match')]
        with op.batch_alter_table('match', schema=None) as batch_op:
            if 'scouting_team_number' in match_cols:
                batch_op.drop_column('scouting_team_number')

    if 'event' in inspector.get_table_names():
        event_cols = [c['name'] for c in inspector.get_columns('event')]
        with op.batch_alter_table('event', schema=None) as batch_op:
            if 'code' in event_cols:
                try:
                    batch_op.create_unique_constraint('uq_event_code', ['code'])
                except Exception:
                    pass
            if 'scouting_team_number' in event_cols:
                batch_op.drop_column('scouting_team_number')
    # ### end Alembic commands ###
