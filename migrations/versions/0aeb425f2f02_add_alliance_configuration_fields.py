"""Add alliance configuration fields

Revision ID: 0aeb425f2f02
Revises: dd3ab3aacc59
Create Date: 2025-08-02 15:34:27.325277

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0aeb425f2f02'
down_revision = 'dd3ab3aacc59'
branch_labels = None
depends_on = None


def upgrade():
    # Defensive migration: only add/drop columns if table/columns exist as expected
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'scouting_alliance' not in inspector.get_table_names():
        # Nothing to do on DBs without this table
        return

    existing = [c['name'] for c in inspector.get_columns('scouting_alliance')]
    with op.batch_alter_table('scouting_alliance', schema=None) as batch_op:
        if 'game_config_team' not in existing:
            batch_op.add_column(sa.Column('game_config_team', sa.Integer(), nullable=True))
        if 'pit_config_team' not in existing:
            batch_op.add_column(sa.Column('pit_config_team', sa.Integer(), nullable=True))
        if 'config_status' not in existing:
            batch_op.add_column(sa.Column('config_status', sa.String(length=50), nullable=True))
        if 'shared_game_config' not in existing:
            batch_op.add_column(sa.Column('shared_game_config', sa.Text(), nullable=True))
        if 'shared_pit_config' not in existing:
            batch_op.add_column(sa.Column('shared_pit_config', sa.Text(), nullable=True))

        # only drop columns if present to avoid KeyError in batch_op
        if 'primary_team_config' in existing:
            try:
                batch_op.drop_column('primary_team_config')
            except Exception:
                pass
        if 'shared_config' in existing:
            try:
                batch_op.drop_column('shared_config')
            except Exception:
                pass

    # ### end Alembic commands ###


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'scouting_alliance' not in inspector.get_table_names():
        return

    existing = [c['name'] for c in inspector.get_columns('scouting_alliance')]
    with op.batch_alter_table('scouting_alliance', schema=None) as batch_op:
        if 'shared_config' not in existing:
            try:
                batch_op.add_column(sa.Column('shared_config', sa.TEXT(), nullable=True))
            except Exception:
                pass
        if 'primary_team_config' not in existing:
            try:
                batch_op.add_column(sa.Column('primary_team_config', sa.INTEGER(), nullable=True))
            except Exception:
                pass

        # drop added columns if present
        for col in ('shared_pit_config', 'shared_game_config', 'config_status', 'pit_config_team', 'game_config_team'):
            if col in existing:
                try:
                    batch_op.drop_column(col)
                except Exception:
                    pass

    # ### end Alembic commands ###
