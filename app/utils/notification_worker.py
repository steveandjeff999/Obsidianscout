"""
Background Notification Worker
Runs as a daemon thread to process pending notifications and update match times
"""
import threading
import time
from datetime import datetime, timedelta
from flask import current_app


def notification_worker(app):
    """
    Background worker that:
    1. Updates match times from APIs every 10 minutes
    2. Schedules notifications for upcoming matches
    3. Processes pending notifications every minute
    4. Cleans up old data periodically
    """
    print("🔔 Notification worker thread started")
    
    last_match_time_update = datetime.min
    last_schedule_check = datetime.min
    last_cleanup = datetime.min
    
    while True:
        try:
            with app.app_context():
                now = datetime.utcnow()
                
                # Update match times every 10 minutes
                if (now - last_match_time_update).total_seconds() >= 600:
                    try:
                        print("\n📅 Updating match times from APIs...")
                        from app.utils.match_time_fetcher import update_all_active_event_times
                        updated_count = update_all_active_event_times()
                        if updated_count > 0:
                            print(f"✅ Updated {updated_count} match times")
                        last_match_time_update = now
                    except Exception as e:
                        print(f"❌ Error updating match times: {e}")
                
                # Schedule notifications for upcoming matches every 5 minutes
                if (now - last_schedule_check).total_seconds() >= 300:
                    try:
                        print("\n📋 Checking for matches to schedule notifications...")
                        schedule_upcoming_match_notifications(app)
                        last_schedule_check = now
                    except Exception as e:
                        print(f"❌ Error scheduling notifications: {e}")
                
                # Process pending notifications every minute
                try:
                    from app.utils.notification_service import process_pending_notifications
                    sent, failed = process_pending_notifications()
                    if sent > 0 or failed > 0:
                        print(f"📬 Notifications sent: {sent}, failed: {failed}")
                except Exception as e:
                    print(f"❌ Error processing notifications: {e}")
                
                # Cleanup old data every hour
                if (now - last_cleanup).total_seconds() >= 3600:
                    try:
                        print("\n🧹 Cleaning up old notification data...")
                        from app.utils.notification_service import cleanup_old_queue_entries
                        from app.utils.push_notifications import cleanup_inactive_devices
                        
                        queue_deleted = cleanup_old_queue_entries(days=7)
                        devices_deleted = cleanup_inactive_devices()
                        
                        if queue_deleted > 0 or devices_deleted > 0:
                            print(f"✅ Cleaned up {queue_deleted} queue entries, {devices_deleted} devices")
                        
                        last_cleanup = now
                    except Exception as e:
                        print(f"❌ Error during cleanup: {e}")
                
            # Sleep for 60 seconds before next cycle
            time.sleep(60)
            
        except Exception as e:
            print(f"❌ Error in notification worker: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)  # Continue after error


def schedule_upcoming_match_notifications(app):
    """
    Find matches in the next 2 hours and schedule notifications for them
    """
    from app.models import Match
    from app.utils.notification_service import schedule_notifications_for_match, get_match_time
    
    now = datetime.utcnow()
    window_end = now + timedelta(hours=2)
    
    # Find matches with scheduled times in the next 2 hours
    matches = Match.query.filter(
        Match.scheduled_time.isnot(None),
        Match.scheduled_time >= now,
        Match.scheduled_time <= window_end
    ).all()
    
    # Also check predicted times
    predicted_matches = Match.query.filter(
        Match.predicted_time.isnot(None),
        Match.predicted_time >= now,
        Match.predicted_time <= window_end
    ).all()
    
    # Combine and deduplicate
    all_matches = list(set(matches + predicted_matches))
    
    if not all_matches:
        return
    
    print(f"📋 Found {len(all_matches)} upcoming matches to check for notifications")
    
    scheduled_total = 0
    for match in all_matches:
        match_time = get_match_time(match)
        if match_time:
            try:
                count = schedule_notifications_for_match(match)
                scheduled_total += count
            except Exception as e:
                print(f"❌ Error scheduling notifications for match {match.id}: {e}")
    
    if scheduled_total > 0:
        print(f"✅ Scheduled {scheduled_total} notifications")


def start_notification_worker(app):
    """
    Start the notification worker thread
    
    Args:
        app: Flask application instance
    """
    worker_thread = threading.Thread(
        target=notification_worker,
        args=(app,),
        daemon=True,
        name='NotificationWorker'
    )
    worker_thread.start()
    return worker_thread
