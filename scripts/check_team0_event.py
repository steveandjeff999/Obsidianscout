"""Check OKOK event for Team 0."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Event
from sqlalchemy import func

app = create_app()

with app.app_context():
    print("Checking OKOK event for Team 0:")
    
    event0 = Event.query.filter(
        func.upper(Event.code) == 'OKOK',
        Event.scouting_team_number == 0
    ).first()
    
    print(f"OKOK event for Team 0: {event0}")
    
    if not event0:
        print("  ⚠️  No event found! Team 0 users would not see any OKOK event.")
        print()
        print("All OKOK events in database:")
        all_events = Event.query.filter(func.upper(Event.code) == 'OKOK').all()
        print(f"  Found {len(all_events)} event(s):")
        for e in all_events:
            print(f"    Event ID {e.id}, Team: {e.scouting_team_number}")
        
        print()
        print("This is CORRECT behavior if:")
        print("  - Team 0 was a test/demo team")
        print("  - Team 0 shouldn't have access to Team 5454's OKOK event")
        print()
        print("This is a PROBLEM if:")
        print("  - Team 0 is supposed to scout at the OKOK event")
        print("  - Team 0's config has event_code='OKOK' but they have no Event record")
    else:
        print(f"  ✓ Found event ID {event0.id} for Team 0")
