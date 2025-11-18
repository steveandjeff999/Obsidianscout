"""Test case-insensitive event lookup with team isolation."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Event
from sqlalchemy import func

app = create_app()

with app.app_context():
    print("Testing case-insensitive event lookup with team isolation:")
    print()
    
    test_code = 'OKOK'
    
    # Test lookup for team 0
    event1 = Event.query.filter(
        func.upper(Event.code) == test_code.upper(),
        Event.scouting_team_number == 0
    ).first()
    
    # Test lookup for team 5454
    event2 = Event.query.filter(
        func.upper(Event.code) == test_code.upper(),
        Event.scouting_team_number == 5454
    ).first()
    
    print(f"Searching for event code: '{test_code}'")
    id1_str = str(event1.id) if event1 else 'None'
    id2_str = str(event2.id) if event2 else 'None'
    print(f"  Team 0:    Event ID {id1_str:>4s}, Code: '{event1.code if event1 else 'N/A'}'")
    print(f"  Team 5454: Event ID {id2_str:>4s}, Code: '{event2.code if event2 else 'N/A'}'")
    print()
    
    if event1 and event2 and event1.id != event2.id:
        print("✓ Teams properly isolated! Each team has its own event record.")
    elif not event1 and not event2:
        print("⚠️  No events found for either team.")
    else:
        print("✗ Isolation may have issues.")
    
    # Test with the new get_event_by_code function
    print()
    print("Testing get_event_by_code() function:")
    from app.utils.team_isolation import get_event_by_code
    from flask_login import login_user, logout_user
    from app.models import User
    
    # Simulate team 0 user
    user0 = User.query.filter_by(scouting_team_number=0).first()
    if user0:
        print(f"  Simulating login as user from Team 0...")
        with app.test_request_context():
            login_user(user0)
            result = get_event_by_code('OKOK')
            print(f"    Result: Event ID {result.id if result else 'None'}, Team: {result.scouting_team_number if result else 'N/A'}")
            logout_user()
    
    # Simulate team 5454 user
    user5454 = User.query.filter_by(scouting_team_number=5454).first()
    if user5454:
        print(f"  Simulating login as user from Team 5454...")
        with app.test_request_context():
            login_user(user5454)
            result = get_event_by_code('OKOK')
            print(f"    Result: Event ID {result.id if result else 'None'}, Team: {result.scouting_team_number if result else 'N/A'}")
            logout_user()
