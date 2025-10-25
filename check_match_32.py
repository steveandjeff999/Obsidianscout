"""Check Match #32 specifically"""
from app import create_app, db
from app.models import Match, Event
from app.models_misc import NotificationQueue
from datetime import timezone
import pytz

app = create_app()

with app.app_context():
    match = Match.query.filter_by(match_number=32).first()
    
    if not match:
        print("❌ Match #32 not found")
        exit(1)
    
    print(f"Match #{match.match_number} ({match.match_type})")
    print(f"Scheduled: {match.scheduled_time}")
    print(f"Predicted: {match.predicted_time}")
    
    if match.predicted_time:
        utc = match.predicted_time.replace(tzinfo=timezone.utc)
        cdt = utc.astimezone(pytz.timezone('America/Chicago'))
        print(f"As CDT: {cdt.strftime('%I:%M %p %Z')}")
    
    print("\nNotifications for this match:")
    queued = NotificationQueue.query.filter_by(match_id=match.id).all()
    for notif in queued:
        print(f"  - scheduled_for: {notif.scheduled_for}")
        print(f"    status: {notif.status}")
        print(f"    sent_at: {notif.sent_at}")
        if notif.scheduled_for:
            utc_send = notif.scheduled_for.replace(tzinfo=timezone.utc)
            cdt_send = utc_send.astimezone(pytz.timezone('America/Chicago'))
            print(f"    As CDT: {cdt_send.strftime('%I:%M %p %Z on %Y-%m-%d')}")
