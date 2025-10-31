"""
Migration: Add schedule_offset to Event table

This adds a schedule_offset column to track how far behind/ahead of schedule each event is running.
The schedule_adjuster module uses this to adjust match time predictions and notification timing.
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def migrate():
    """Add schedule_offset column to Event table"""
    from app import create_app, db
    from app.models import Event
    from sqlalchemy import inspect, text
    
    app = create_app()
    
    with app.app_context():
        print(" Checking Event table for schedule_offset column...")
        
        # Check if column already exists
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('event')]
        
        if 'schedule_offset' in columns:
            print(" schedule_offset column already exists")
            return
        
        print(" Adding schedule_offset column to Event table...")
        
        # Add the column using raw SQL (more reliable than alembic for simple additions)
        try:
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE event ADD COLUMN schedule_offset INTEGER"
                ))
                conn.commit()
            
            print(" Successfully added schedule_offset column")
            print("\nColumn details:")
            print("  - Type: INTEGER")
            print("  - Nullable: Yes (NULL = no adjustment calculated yet)")
            print("  - Purpose: Stores event schedule offset in minutes")
            print("    - Positive = event is behind schedule")
            print("    - Negative = event is ahead of schedule")
            print("    - NULL/0 = on schedule or not yet calculated")
            
        except Exception as e:
            print(f" Error adding column: {e}")
            import traceback
            traceback.print_exc()
            return
        
        print("\n Migration completed successfully!")
        print("\nThe schedule_adjuster module will now be able to:")
        print("  1. Detect when events are running behind/ahead of schedule")
        print("  2. Adjust future match time predictions")
        print("  3. Automatically reschedule notifications to send at correct times")

if __name__ == '__main__':
    migrate()
