"""Add StrategyDrawing model for per-match strategy drawings

Revision ID: 35fba2c73d42
Revises: 
Create Date: 2025-07-22 19:14:17.268654

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '35fba2c73d42'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('sync_participant')
    op.drop_table('sync_session')
    op.drop_table('offline_data_queue')
    op.drop_table('device_connection')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('device_connection',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('device_id', sa.VARCHAR(length=100), nullable=False),
    sa.Column('device_name', sa.VARCHAR(length=100), nullable=False),
    sa.Column('device_type', sa.VARCHAR(length=50), nullable=False),
    sa.Column('user_id', sa.INTEGER(), nullable=True),
    sa.Column('is_online', sa.BOOLEAN(), nullable=True),
    sa.Column('last_seen', sa.DATETIME(), nullable=True),
    sa.Column('connection_status', sa.VARCHAR(length=50), nullable=True),
    sa.Column('bluetooth_address', sa.VARCHAR(length=50), nullable=True),
    sa.Column('bluetooth_name', sa.VARCHAR(length=100), nullable=True),
    sa.Column('is_bluetooth_enabled', sa.BOOLEAN(), nullable=True),
    sa.Column('auto_sync_enabled', sa.BOOLEAN(), nullable=True),
    sa.Column('sync_interval', sa.INTEGER(), nullable=True),
    sa.Column('last_sync', sa.DATETIME(), nullable=True),
    sa.Column('can_host_sync', sa.BOOLEAN(), nullable=True),
    sa.Column('can_join_sync', sa.BOOLEAN(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('updated_at', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_id')
    )
    op.create_table('offline_data_queue',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('device_id', sa.VARCHAR(length=100), nullable=False),
    sa.Column('data_type', sa.VARCHAR(length=50), nullable=False),
    sa.Column('data_id', sa.VARCHAR(length=100), nullable=False),
    sa.Column('data_json', sa.TEXT(), nullable=False),
    sa.Column('status', sa.VARCHAR(length=50), nullable=True),
    sa.Column('priority', sa.INTEGER(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('synced_at', sa.DATETIME(), nullable=True),
    sa.Column('retry_count', sa.INTEGER(), nullable=True),
    sa.Column('max_retries', sa.INTEGER(), nullable=True),
    sa.ForeignKeyConstraint(['device_id'], ['device_connection.device_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sync_session',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('session_id', sa.VARCHAR(length=36), nullable=False),
    sa.Column('host_device_id', sa.VARCHAR(length=100), nullable=False),
    sa.Column('status', sa.VARCHAR(length=50), nullable=True),
    sa.Column('started_at', sa.DATETIME(), nullable=True),
    sa.Column('completed_at', sa.DATETIME(), nullable=True),
    sa.Column('data_sent', sa.INTEGER(), nullable=True),
    sa.Column('data_received', sa.INTEGER(), nullable=True),
    sa.Column('sync_duration', sa.FLOAT(), nullable=True),
    sa.Column('error_message', sa.TEXT(), nullable=True),
    sa.ForeignKeyConstraint(['host_device_id'], ['device_connection.device_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id')
    )
    op.create_table('sync_participant',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('session_id', sa.VARCHAR(length=36), nullable=False),
    sa.Column('device_id', sa.VARCHAR(length=100), nullable=False),
    sa.Column('joined_at', sa.DATETIME(), nullable=True),
    sa.Column('left_at', sa.DATETIME(), nullable=True),
    sa.Column('status', sa.VARCHAR(length=50), nullable=True),
    sa.Column('data_sent', sa.INTEGER(), nullable=True),
    sa.Column('data_received', sa.INTEGER(), nullable=True),
    sa.ForeignKeyConstraint(['device_id'], ['device_connection.device_id'], ),
    sa.ForeignKeyConstraint(['session_id'], ['sync_session.session_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###
