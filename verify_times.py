"""Verify what times are actually stored vs displayed"""
from app import create_app, db
from app.models import Match, Event
from app.models_misc import NotificationQueue
from datetime import timezone
import pytz

app = create_app()

with app.app_context():
    # Find matches with predicted times
    matches = Match.query.filter(Match.predicted_time.isnot(None)).limit(5).all()
    
    for match in matches:
        event = Event.query.get(match.event_id) if match.event_id else None
        event_tz_str = event.timezone if event else None
        
        print(f"\n{'='*80}")
        print(f"Match #{match.match_number} ({match.match_type})")
        print(f"Event: {event.name if event else 'Unknown'} (TZ: {event_tz_str})")
        print(f"{'='*80}")
        
        # Show what's in DB
        print(f"Database value (naive): {match.predicted_time}")
        
        if event_tz_str:
            event_tz = pytz.timezone(event_tz_str)
            
            # What the code SHOULD do: treat DB value as UTC
            as_utc = match.predicted_time.replace(tzinfo=timezone.utc)
            as_local_correct = as_utc.astimezone(event_tz)
            print(f"\nCORRECT interpretation (DB = UTC):")
            print(f"   {match.predicted_time} (DB) → {as_utc} (UTC) → {as_local_correct.strftime('%I:%M %p %Z')} (display)")
            
            # What it might be doing WRONG: treating DB value as local time
            as_local_wrong = event_tz.localize(match.predicted_time)
            as_utc_wrong = as_local_wrong.astimezone(timezone.utc)
            print(f"\nWRONG interpretation (DB = Local):")
            print(f"   {match.predicted_time} (DB) → {as_local_wrong.strftime('%I:%M %p %Z')} (local) → {as_utc_wrong} (UTC)")
            
            # Show the 5-hour difference
            diff_hours = (as_utc - as_utc_wrong).total_seconds() / 3600
            print(f"\n⏱️  Time difference: {abs(diff_hours):.1f} hours")
            
            if abs(diff_hours) == 5:
                print(f"   Warning: This is exactly CDT offset - confirms timezone bug!")
