"""Enable cascade delete for pit_scouting_data.event_id

Revision ID: d7e2f3a4b5c6
Revises: c6f1a2b3d4e5
Create Date: 2026-04-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7e2f3a4b5c6'
down_revision = 'c6f1a2b3d4e5'
branch_labels = None
depends_on = None


def _get_event_fk(inspector):
    try:
        for fk in inspector.get_foreign_keys('pit_scouting_data'):
            if fk.get('referred_table') == 'event' and fk.get('constrained_columns') == ['event_id']:
                return fk
    except Exception:
        return None
    return None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'pit_scouting_data' not in existing_tables:
        return

    fk = _get_event_fk(inspector)
    if not fk:
        return

    current_name = fk.get('name') or 'pit_scouting_data_event_id_fkey'
    options = fk.get('options') or {}
    if options.get('ondelete') == 'CASCADE':
        return

    op.drop_constraint(current_name, 'pit_scouting_data', type_='foreignkey')
    op.create_foreign_key(
        'pit_scouting_data_event_id_fkey',
        'pit_scouting_data',
        'event',
        ['event_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if 'pit_scouting_data' not in existing_tables:
        return

    fk = _get_event_fk(inspector)
    if not fk:
        return

    current_name = fk.get('name') or 'pit_scouting_data_event_id_fkey'
    options = fk.get('options') or {}
    if options.get('ondelete') != 'CASCADE':
        return

    op.drop_constraint(current_name, 'pit_scouting_data', type_='foreignkey')
    op.create_foreign_key(
        'pit_scouting_data_event_id_fkey',
        'pit_scouting_data',
        'event',
        ['event_id'],
        ['id'],
    )
