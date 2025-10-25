"""
Timezone Diagnostic Script
Run this to see what's actually stored in the database and how it's being interpreted
"""
from app import create_app, db
from app.models import Match, Event, User
from app.models_misc import NotificationQueue
from datetime import datetime, timezone
import pytz

app = create_app()

with app.app_context():
    print("=" * 80)
    print("TIMEZONE DIAGNOSTIC REPORT")
    print("=" * 80)
    
    # Find a match with a predicted time
    match = Match.query.filter(Match.predicted_time.isnot(None)).first()
    
    if not match:
        print("\n❌ No matches with predicted times found")
        exit(1)
    
    print(f"\n📋 MATCH #{match.match_number} ({match.match_type})")
    print("-" * 80)
    
    # Get event timezone
    event = Event.query.get(match.event_id)
    event_tz_str = event.timezone if event else None
    print(f"Event: {event.name if event else 'Unknown'}")
    print(f"Event Timezone Setting: {event_tz_str}")
    
    # Show raw database values
    print(f"\n📊 RAW DATABASE VALUES:")
    print(f"  scheduled_time: {match.scheduled_time}")
    print(f"  predicted_time: {match.predicted_time}")
    print(f"  Type: {type(match.predicted_time)}")
    print(f"  Has tzinfo: {match.predicted_time.tzinfo is not None}")
    
    # Show what happens when we treat as UTC
    if match.predicted_time:
        naive_time = match.predicted_time
        print(f"\n🔍 INTERPRETATION AS UTC:")
        
        # This is what the code currently does
        as_utc = naive_time.replace(tzinfo=timezone.utc)
        print(f"  Naive time: {naive_time}")
        print(f"  Labeled as UTC: {as_utc}")
        print(f"  As ISO: {as_utc.isoformat()}")
        
        # Convert to CDT to see what time that would be locally
        if event_tz_str:
            try:
                event_tz = pytz.timezone(event_tz_str)
                as_local = as_utc.astimezone(event_tz)
                print(f"  Converted to {event_tz_str}: {as_local}")
                print(f"  Display format: {as_local.strftime('%I:%M %p %Z')}")
            except Exception as e:
                print(f"  ⚠️  Could not convert to event timezone: {e}")
        
        # Show current time for reference
        now_utc = datetime.now(timezone.utc)
        print(f"\n⏰ CURRENT TIME:")
        print(f"  UTC: {now_utc}")
        if event_tz_str:
            try:
                event_tz = pytz.timezone(event_tz_str)
                now_local = now_utc.astimezone(event_tz)
                print(f"  {event_tz_str}: {now_local}")
            except:
                pass
    
    # Check notification queue
    print(f"\n📬 NOTIFICATION QUEUE:")
    queued = NotificationQueue.query.filter_by(match_id=match.id).all()
    if queued:
        for notif in queued:
            print(f"  ID {notif.id}:")
            print(f"    scheduled_for: {notif.scheduled_for} (naive)")
            if notif.scheduled_for:
                as_utc = notif.scheduled_for.replace(tzinfo=timezone.utc)
                if event_tz_str:
                    try:
                        event_tz = pytz.timezone(event_tz_str)
                        as_local = as_utc.astimezone(event_tz)
                        print(f"    If UTC → {event_tz_str}: {as_local.strftime('%I:%M %p %Z')}")
                    except:
                        pass
            print(f"    status: {notif.status}")
            print(f"    sent_at: {notif.sent_at}")
    else:
        print("  (No notifications queued for this match)")
    
    print("\n" + "=" * 80)
    print("DIAGNOSIS:")
    print("=" * 80)
    
    if match.predicted_time and event_tz_str:
        naive = match.predicted_time
        as_utc = naive.replace(tzinfo=timezone.utc)
        event_tz = pytz.timezone(event_tz_str)
        as_local = as_utc.astimezone(event_tz)
        
        # The time displayed in UI
        display_time = as_local.strftime('%I:%M %p %Z')
        
        print(f"\n1. Database stores: {naive} (naive datetime)")
        print(f"2. Code treats as: {as_utc} (UTC)")
        print(f"3. Displays to user as: {display_time}")
        print(f"\nIf notifications are sending ~5 hours early, the database")
        print(f"likely contains LOCAL times ({event_tz_str}) but code treats them as UTC.")
        print(f"\nExpected DB value for {display_time} display:")
        print(f"  Should be: {as_local.astimezone(timezone.utc).replace(tzinfo=None)} (UTC without tz)")
        print(f"  Actually is: {naive}")
        
        if naive.hour == as_local.hour:
            print(f"\n⚠️  PROBLEM DETECTED: Database time matches LOCAL hour!")
            print(f"   Times are being stored as {event_tz_str} instead of UTC!")
        else:
            print(f"\n✅ Database appears correct (UTC storage)")
