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
from app import db

# Module-level tracker for the last time we ran the "schedule upcoming matches" check.
# This is intentionally module-level so other parts of the app (routes/templates)
# can query how long until the next scheduled run.
last_schedule_check_time = None
# Cache of last-known event schedule_offset values so we only reschedule notifications
# when the offset changes meaningfully. Keyed by event.id -> int(offset_minutes)
last_event_offsets = {}

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
    print(" Notification worker thread started")

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
                        print("\n Updating match times from APIs...")
                        # This import is assumed to work in the Flask context
                        from app.utils.match_time_fetcher import update_all_active_event_times
                        updated_count = update_all_active_event_times()
                        if updated_count > 0:
                            print(f" Updated {updated_count} match times")
                        last_match_time_update = now
                    except Exception as e:
                        print(f" Error updating match times: {e}")

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
                                print(f"️  Event {result['event_code']} is {abs(offset):.0f} min "
                                      f"{'behind' if offset > 0 else 'ahead of'} schedule")

                        last_schedule_adjustment = now
                    except Exception as e:
                        print(f" Error checking schedule adjustments: {e}")
                        traceback.print_exc()

                # Schedule notifications for upcoming matches every 5 minutes
                # Update module-level last_schedule_check_time so other code can inspect it
                if (now - last_schedule_check_time).total_seconds() >= 300:
                    try:
                        print("\n Checking for matches to schedule notifications...")
                        schedule_upcoming_match_notifications(app)
                        # Record when we performed the schedule check
                        last_schedule_check_time = now
                    except Exception as e:
                        print(f" Error scheduling notifications: {e}")

                # Process pending notifications every minute
                try:
                    # This import is assumed to work in the Flask context
                    from app.utils.notification_service import process_pending_notifications
                    sent, failed = process_pending_notifications()
                    if sent > 0 or failed > 0:
                        print(f" Notifications sent: {sent}, failed: {failed}")
                except Exception as e:
                    print(f" Error processing notifications: {e}")

                # Cleanup old data every hour
                if (now - last_cleanup).total_seconds() >= 3600:
                    try:
                        print("\n Cleaning up old notification data...")
                        # These imports are assumed to work in the Flask context
                        from app.utils.notification_service import cleanup_old_queue_entries
                        from app.utils.push_notifications import cleanup_inactive_devices

                        queue_deleted = cleanup_old_queue_entries(days=7)
                        devices_deleted = cleanup_inactive_devices()

                        if queue_deleted > 0 or devices_deleted > 0:
                            print(f" Cleaned up {queue_deleted} queue entries, {devices_deleted} devices")

                        last_cleanup = now
                    except Exception as e:
                        print(f" Error during cleanup: {e}")

            # Sleep for 60 seconds before next cycle
            time.sleep(60)

        except Exception as e:
            print(f" Error in notification worker: {e}")
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

    # Database may store naive datetimes that represent event-local times
    # (varies by import source). To be robust we query a broader window and
    # filter in Python using get_match_time(), which will return a timezone-
    # aware UTC datetime after interpreting naive values correctly.
    lookback = timedelta(days=1)
    extended_start = (now - lookback).replace(tzinfo=None)
    extended_end = (window_end + lookback).replace(tzinfo=None)

    candidates = Match.query.filter(
        Match.scheduled_time.isnot(None),
        Match.scheduled_time >= extended_start,
        Match.scheduled_time <= extended_end
    ).all()

    # Also include matches with predicted times in the extended window
    predicted_candidates = Match.query.filter(
        Match.predicted_time.isnot(None),
        Match.predicted_time >= extended_start,
        Match.predicted_time <= extended_end
    ).all()

    # Combine and deduplicate candidate matches
    all_matches = list({m.id: m for m in (candidates + predicted_candidates)}.values())

    if not all_matches:
        return

    print(f" Found {len(all_matches)} upcoming matches to check for notifications")

    scheduled_total = 0
    for match in all_matches:
        # Use get_match_time to interpret naive DB values properly and get UTC-aware time
        match_time = get_match_time(match)
        if not match_time:
            continue

        # Only schedule matches that actually fall in our target window (now..window_end)
        if match_time < now or match_time > window_end:
            # Skip matches outside the real UTC window
            continue

        try:
            count = schedule_notifications_for_match(match)
            scheduled_total += count
        except Exception as e:
            print(f" Error scheduling notifications for match {match.id}: {e}")

    if scheduled_total > 0:
        print(f" Scheduled {scheduled_total} notifications")

    # Schedule end-of-day summaries (runs each time we check upcoming matches)
    try:
        summary_count = schedule_end_of_day_summaries()
        if summary_count > 0:
            print(f" Scheduled {summary_count} end-of-day summary notifications")
    except Exception as e:
        print(f" Error scheduling end-of-day summaries: {e}")

    # Lightweight reschedule pass: when an event has a significant schedule_offset (>= 15 minutes)
    # we should reschedule pending notifications for that event's future matches so they fire
    # relative to the updated timetable. We avoid running the heavy schedule_adjuster here
    # (which queries external APIs) and instead rely on the persisted Event.schedule_offset
    # value computed by the schedule_adjuster. This check runs every 5 minutes (same cadence
    # as scheduling) so notifications react quickly when offsets are detected.
    try:
        rescheduled_total = 0
        from app.models import Event, Match
        from app.models_misc import NotificationQueue
        from app.utils.notification_service import schedule_notifications_for_match

        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)

        # Find events with non-null schedule_offset
        events = Event.query.filter(Event.schedule_offset.isnot(None)).all()
        for event in events:
            try:
                offset = int(event.schedule_offset or 0)
                # Only act on significant offsets (15+ minutes)
                if abs(offset) < 15:
                    continue

                prev = last_event_offsets.get(event.id)
                # If offset hasn't changed since last time we rescheduled for this event,
                # skip to avoid repeated reschedules.
                if prev == offset:
                    continue

                # Find future matches for this event (compare against naive DB times)
                future_matches = Match.query.filter(
                    Match.event_id == event.id,
                    Match.scheduled_time.isnot(None),
                    Match.scheduled_time > now_naive
                ).all()

                if not future_matches:
                    # Still update cache so we don't repeatedly check empty events
                    last_event_offsets[event.id] = offset
                    continue

                # Clear pending queue entries for these future matches so they can be recreated
                match_ids = [m.id for m in future_matches]
                pending = NotificationQueue.query.filter(
                    NotificationQueue.match_id.in_(match_ids),
                    NotificationQueue.status == 'pending'
                ).all()

                if pending:
                    for q in pending:
                        db.session.delete(q)
                    db.session.commit()
                    print(f"  Cleared {len(pending)} pending notifications for event {event.code} due to offset {offset}m")

                # Reschedule notifications based on adjusted predicted times (if any)
                for m in future_matches:
                    try:
                        cnt = schedule_notifications_for_match(m)
                        rescheduled_total += cnt
                    except Exception as e:
                        print(f" Error rescheduling notifications for match {m.id}: {e}")

                # Record that we've handled this offset value for this event
                last_event_offsets[event.id] = offset

            except Exception as e:
                print(f" Error handling reschedule logic for event {getattr(event,'code', 'N/A')}: {e}")

        if rescheduled_total > 0:
            print(f" Rescheduled {rescheduled_total} notifications due to significant schedule offsets")
    except Exception as e:
        print(f" Error in lightweight reschedule pass: {e}")


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
