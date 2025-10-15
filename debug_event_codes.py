"""
Check what event codes are actually in the database
"""
from app import create_app, db
from app.models import Event

app = create_app()

with app.app_context():
    events = Event.query.all()
    
    print("Events in database:")
    print("=" * 80)
    
    for event in events:
        print(f"\nEvent ID: {event.id}")
        print(f"Name: {event.name}")
        print(f"Code: {event.code}")
        print(f"Year: {event.year}")
        print(f"Timezone: {event.timezone}")
        print(f"Location: {event.location}")
