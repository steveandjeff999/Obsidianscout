"""
Background Notification Worker
Runs as a daemon thread to process pending notifications and update match times
"""
import threading
import time
import os
import json # Added missing import
import atexit # Added missing import
import traceback # Added missing import for error reporting
from datetime import datetime, timezone, timedelta
from flask import current_app

# Module-level tracker for the last time we ran the "schedule upcoming matches" check.
# This is intentionally module-level so other parts of the app (routes/templates)
# can query how long until the next scheduled run.
last_schedule_check_time = None

# Leader lock file ensures only one process on this host runs the scheduler.
# We use an atomic create (O_EXCL) strategy and write JSON containing pid/timestamp
# so other processes can detect a stale lock and take over if necessary.
def _lock_path_for_app(app):
    """Determines the path for the host-local lock file."""
    # Use instance path if available, else fallback to cwd
    try:
        base = app.instance_path or os.getcwd()
    except Exception:
        base = os.getcwd()
    return os.path.join(base, 'notification_worker.lock')


def acquire_leader_lock(app, stale_seconds=600):
    """Try to acquire a host-local leader lock. Returns True if acquired."""
    lock_path = _lock_path_for_app(app)
    pid = os.getpid()
    now = datetime.now(timezone.utc).isoformat()

    # First attempt: atomic creation
    try:
        # Use os.O_EXCL to fail if file exists
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            os.write(fd, json.dumps({'pid': pid, 'ts': now}).encode('utf-8'))
        finally:
            os.close(fd)

        # Register cleanup to remove the lock on exit
        def _cleanup():
            try:
                if os.path.exists(lock_path):
                    # Only remove if we own it (pid matches)
                    with open(lock_path, 'r') as fh:
                        try:
                            data = json.load(fh)
                        except Exception:
                            data = None
                    if data and int(data.get('pid', -1)) == pid:
                        os.remove(lock_path)
            except Exception:
                # Silently fail cleanup if error occurs
                pass

        atexit.register(_cleanup)
        return True
    except FileExistsError:
        # Check whether the existing lock is stale
        try:
            with open(lock_path, 'r') as fh:
                data = json.load(fh)
        except Exception:
            data = None

        if data:
            try:
                ts = datetime.fromisoformat(data.get('ts'))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > stale_seconds:
                    # Try to take over: remove stale lock and create ours
                    try:
                        os.remove(lock_path)
                    except Exception:
                        # Someone else may beat us; fail gracefully
                        return False

                    try:
                        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                        try:
                            os.write(fd, json.dumps({'pid': pid, 'ts': now}).encode('utf-8'))
                        finally:
                            os.close(fd)

                        # Register cleanup
                        def _cleanup2():
                            try:
                                if os.path.exists(lock_path):
                                    with open(lock_path, 'r') as fh:
                                        try:
                                            data2 = json.load(fh)
                                        except Exception:
                                            data2 = None
                                    if data2 and int(data2.get('pid', -1)) == pid:
                                        os.remove(lock_path)
                            except Exception:
                                pass

                        atexit.register(_cleanup2)
                        return True
                    except FileExistsError:
                        return False
            except Exception:
                return False

        return False

def notification_worker(app):
    """
    Background worker that:
    1. Updates match times from APIs every 10 minutes
    2. Schedules notifications for upcoming matches
    3. Processes pending notifications every minute
    4. Cleans up old data periodically
    """
    print("🔔 Notification worker thread started")

    # Use timezone-aware datetime.min to avoid mixing naive and aware datetimes
    last_match_time_update = datetime.min.replace(tzinfo=timezone.utc)
    # Initialize module-level last_schedule_check_time on worker start
    global last_schedule_check_time
    last_schedule_check_time = datetime.min.replace(tzinfo=timezone.utc)
    last_schedule_adjustment = datetime.min.replace(tzinfo=timezone.utc)
    last_cleanup = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        try:
            with app.app_context():
                now = datetime.now(timezone.utc)

                # Update match times every 10 minutes
                if (now - last_match_time_update).total_seconds() >= 600:
                    try:
                        print("\n📅 Updating match times from APIs...")
                        # This import is assumed to work in the Flask context
                        from app.utils.match_time_fetcher import update_all_active_event_times
                        updated_count = update_all_active_event_times()
                        if updated_count > 0:
                            print(f"✅ Updated {updated_count} match times")
                        last_match_time_update = now
                    except Exception as e:
                        print(f"❌ Error updating match times: {e}")

                # Check for schedule adjustments every 15 minutes
                if (now - last_schedule_adjustment).total_seconds() >= 900:
                    try:
                        print("\n⏱️  Checking for schedule delays/advances...")
                        # This import is assumed to work in the Flask context
                        from app.utils.schedule_adjuster import update_all_active_events_schedule
                        results = update_all_active_events_schedule()

                        # Log significant adjustments
                        for result in results:
                            if result.get('success') and result.get('adjusted_matches', 0) > 0:
                                offset = result.get('analysis', {}).get('recent_offset_minutes', 0)
                                print(f"⚠️  Event {result['event_code']} is {abs(offset):.0f} min "
                                      f"{'behind' if offset > 0 else 'ahead of'} schedule")

                        last_schedule_adjustment = now
                    except Exception as e:
                        print(f"❌ Error checking schedule adjustments: {e}")
                        traceback.print_exc()

                # Schedule notifications for upcoming matches every 5 minutes
                # Update module-level last_schedule_check_time so other code can inspect it
                if (now - last_schedule_check_time).total_seconds() >= 300:
                    try:
                        print("\n📋 Checking for matches to schedule notifications...")
                        schedule_upcoming_match_notifications(app)
                        # Record when we performed the schedule check
                        last_schedule_check_time = now
                    except Exception as e:
                        print(f"❌ Error scheduling notifications: {e}")

                # Process pending notifications every minute
                try:
                    # This import is assumed to work in the Flask context
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
                        # These imports are assumed to work in the Flask context
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
            traceback.print_exc()
            time.sleep(60)  # Continue after error


def schedule_upcoming_match_notifications(app):
    """
    Find matches in the next 2 hours and schedule notifications for them
    """
    # These imports are assumed to work in the Flask context
    from app.models import Match
    from app.utils.notification_service import schedule_notifications_for_match, get_match_time
    # Also import the new end-of-day summary scheduler
    from app.utils.notification_service import schedule_end_of_day_summaries

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=2)

    # Convert to naive UTC for database comparison (SQLite stores naive datetimes)
    now_naive = now.replace(tzinfo=None)
    window_end_naive = window_end.replace(tzinfo=None)

    # Find matches with scheduled times in the next 2 hours
    matches = Match.query.filter(
        Match.scheduled_time.isnot(None),
        Match.scheduled_time >= now_naive,
        Match.scheduled_time <= window_end_naive
    ).all()

    # Also check predicted times
    predicted_matches = Match.query.filter(
        Match.predicted_time.isnot(None),
        Match.predicted_time >= now_naive,
        Match.predicted_time <= window_end_naive
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

    # Schedule end-of-day summaries (runs each time we check upcoming matches)
    try:
        summary_count = schedule_end_of_day_summaries()
        if summary_count > 0:
            print(f"✅ Scheduled {summary_count} end-of-day summary notifications")
    except Exception as e:
        print(f"❌ Error scheduling end-of-day summaries: {e}")


def get_seconds_until_next_schedule():
    """
    Return the number of seconds until the next 5-minute scheduling run.
    If the worker hasn't run yet, returns 0.
    This helper is safe to call from routes/templates to show an ETA to users.
    """
    global last_schedule_check_time
    try:
        now = datetime.now(timezone.utc)
        if last_schedule_check_time is None or last_schedule_check_time.replace(tzinfo=None) == datetime.min.replace(tzinfo=None):
             # Check if it's the initial (min) value
             return 0

        elapsed = (now - last_schedule_check_time).total_seconds()
        remaining = 300 - elapsed
        return int(remaining) if remaining > 0 else 0
    except Exception:
        return 0


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
