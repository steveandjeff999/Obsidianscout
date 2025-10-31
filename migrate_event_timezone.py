"""
Database Migration: Add timezone field to Event model
This migration adds a timezone column to store IANA timezone strings (e.g., 'America/Denver')
"""
from datetime import datetime, timezone
from app import db
from app.models import Event
from sqlalchemy import text
import sys


def add_timezone_column():
    """Add timezone column to event table"""
    print("Adding timezone column to event table...")
    
    try:
        # Check if column already exists
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('event')]
        
        if 'timezone' in columns:
            print(" Timezone column already exists, skipping creation")
            return True
        
        # Add the column using raw SQL
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE event ADD COLUMN timezone VARCHAR(50)'))
            conn.commit()
        
        print(" Successfully added timezone column")
        return True
        
    except Exception as e:
        print(f" Error adding timezone column: {e}")
        return False


def backfill_timezones_from_api():
    """
    Backfill timezone information for existing events by fetching from TBA API
    """
    print("\nBackfilling timezone data for existing events...")
    
    try:
        from app.utils.api_utils import get_event_details_dual_api
        
        # Get all events that don't have timezone set
        events = Event.query.filter(
            (Event.timezone == None) | (Event.timezone == '')
        ).all()
        
        if not events:
            print(" No events need timezone backfill")
            return True
        
        print(f"Found {len(events)} events without timezone information")
        
        updated_count = 0
        failed_count = 0
        
        for event in events:
            if not event.code:
                print(f"️  Event {event.id} has no code, skipping")
                continue
            
            try:
                print(f"  Fetching timezone for event {event.code}...")
                event_details = get_event_details_dual_api(event.code)
                
                if event_details and event_details.get('timezone'):
                    event.timezone = event_details['timezone']
                    
                    # Also update other fields if they're missing
                    if not event.location and event_details.get('location'):
                        event.location = event_details['location']
                    if not event.start_date and event_details.get('start_date'):
                        event.start_date = event_details['start_date']
                    if not event.end_date and event_details.get('end_date'):
                        event.end_date = event_details['end_date']
                    
                    updated_count += 1
                    print(f"   Set timezone to {event.timezone}")
                else:
                    print(f"  ️  No timezone data available from API")
                    failed_count += 1
                    
            except Exception as e:
                print(f"   Error fetching details for {event.code}: {e}")
                failed_count += 1
        
        # Commit all changes
        db.session.commit()
        
        print(f"\n Backfill complete: {updated_count} events updated, {failed_count} failed")
        return True
        
    except Exception as e:
        print(f" Error during backfill: {e}")
        db.session.rollback()
        return False


def run_migration():
    """Run the full migration"""
    print("=" * 60)
    print("EVENT TIMEZONE MIGRATION")
    print("=" * 60)
    print()
    
    # Step 1: Add column
    if not add_timezone_column():
        print("\n Migration failed at column creation step")
        return False
    
    # Step 2: Backfill data
    if not backfill_timezones_from_api():
        print("\n Migration failed at backfill step")
        print("️  Column was created but some events may not have timezone data")
        return False
    
    print("\n" + "=" * 60)
    print(" MIGRATION COMPLETED SUCCESSFULLY")
    print("=" * 60)
    print("\nNext steps:")
    print("1. New events will automatically have timezone populated from API")
    print("2. Match times will be displayed in event local timezone")
    print("3. Notifications will be sent at correct local times")
    print()
    
    return True


if __name__ == '__main__':
    print("This migration should be run through the Flask app context")
    print("Use: python -c \"from app import create_app, db; from migrate_event_timezone import run_migration; app = create_app(); app.app_context().push(); run_migration()\"")
    sys.exit(1)
