"""Enable cascade delete for scouting_data.match_id

Revision ID: c6f1a2b3d4e5
Revises: e4b7c9a2d1f6
Create Date: 2026-04-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6f1a2b3d4e5'
down_revision = 'e4b7c9a2d1f6'
branch_labels = None
depends_on = None


def _get_match_fk(inspector):
    try:
        for fk in inspector.get_foreign_keys('scouting_data'):
            if fk.get('referred_table') == 'match' and fk.get('constrained_columns') == ['match_id']:
                return fk
    except Exception:
        return None
    return None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'scouting_data' not in existing_tables:
        return

    fk = _get_match_fk(inspector)
    if not fk:
        return

    current_name = fk.get('name') or 'scouting_data_match_id_fkey'
    options = fk.get('options') or {}
    if options.get('ondelete') == 'CASCADE':
        return

    op.drop_constraint(current_name, 'scouting_data', type_='foreignkey')
    op.create_foreign_key(
        'scouting_data_match_id_fkey',
        'scouting_data',
        'match',
        ['match_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'scouting_data' not in existing_tables:
        return

    fk = _get_match_fk(inspector)
    if not fk:
        return

    current_name = fk.get('name') or 'scouting_data_match_id_fkey'
    options = fk.get('options') or {}
    if options.get('ondelete') != 'CASCADE':
        return

    op.drop_constraint(current_name, 'scouting_data', type_='foreignkey')
    op.create_foreign_key(
        'scouting_data_match_id_fkey',
        'scouting_data',
        'match',
        ['match_id'],
        ['id'],
    )
