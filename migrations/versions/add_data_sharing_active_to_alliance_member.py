"""Add is_data_sharing_active to scouting_alliance_member

Revision ID: f5d8a2b9c3e7
Revises: 
Create Date: 2024-12-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5d8a2b9c3e7'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add is_data_sharing_active column to scouting_alliance_member
    # Default to True for existing members
    try:
        op.add_column('scouting_alliance_member', 
            sa.Column('is_data_sharing_active', sa.Boolean(), nullable=True, default=True))
    except Exception as e:
        print(f"Column is_data_sharing_active may already exist: {e}")
    
    try:
        op.add_column('scouting_alliance_member',
            sa.Column('data_sharing_deactivated_at', sa.DateTime(), nullable=True))
    except Exception as e:
        print(f"Column data_sharing_deactivated_at may already exist: {e}")
    
    # Update existing rows to have is_data_sharing_active = True
    try:
        op.execute("UPDATE scouting_alliance_member SET is_data_sharing_active = 1 WHERE is_data_sharing_active IS NULL")
    except Exception as e:
        print(f"Could not update existing rows: {e}")


def downgrade():
    try:
        op.drop_column('scouting_alliance_member', 'data_sharing_deactivated_at')
    except Exception:
        pass
    
    try:
        op.drop_column('scouting_alliance_member', 'is_data_sharing_active')
    except Exception:
        pass
