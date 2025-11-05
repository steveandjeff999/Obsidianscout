"""
Notifications Routes
Handles notification subscriptions, device registration, and testing
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Match, Team, Event
from app.models_misc import NotificationSubscription, DeviceToken, NotificationLog
from app.utils.notification_service import (
    send_notification_for_subscription,
    get_user_notification_history,
    schedule_notifications_for_match
)
from app.utils.push_notifications import register_device, get_vapid_keys, send_push_to_user
from app.utils.emailer import send_email
from datetime import datetime, timezone, timedelta
from app.utils.notification_worker import get_seconds_until_next_schedule

bp = Blueprint('notifications', __name__, url_prefix='/notifications')


@bp.route('/')
@login_required
def index():
    """Notification management page"""
    # Get user's subscriptions
    subscriptions = NotificationSubscription.query.filter_by(
        user_id=current_user.id
    ).order_by(NotificationSubscription.created_at.desc()).all()
    
    # Get user's devices
    devices = DeviceToken.query.filter_by(
        user_id=current_user.id
    ).order_by(DeviceToken.created_at.desc()).all()
    
    # Get notification history
    history = get_user_notification_history(current_user.id, limit=50)
    # Annotate each history log with event timezone (if available) so templates can
    # display sent times in the event local timezone instead of UTC.
    try:
        for log in history:
            tz = None
            # Prefer explicit event_code stored on the log
            if getattr(log, 'event_code', None):
                ev = Event.query.filter_by(code=log.event_code, scouting_team_number=current_user.scouting_team_number).first()
                if ev and getattr(ev, 'timezone', None):
                    tz = ev.timezone

            # Fallback: if log references a match, derive the event from the match
            if not tz and getattr(log, 'match_id', None):
                try:
                    m = Match.query.get(log.match_id)
                    if m and getattr(m, 'event_id', None):
                        ev2 = Event.query.get(m.event_id)
                        if ev2 and getattr(ev2, 'timezone', None):
                            tz = ev2.timezone
                except Exception:
                    tz = None

            # Attach attribute for template usage (Jinja can access it)
            setattr(log, 'event_timezone', tz)
    except Exception as e:
        # Fail gracefully; templates will fall back to UTC formatting
        print(f"Warning: could not resolve event timezone for history logs: {e}")
    
    # Get pending notifications (scheduled to send in the future)
    # Note: Match data is in different database, so we fetch separately and join in Python
    from app.models_misc import NotificationQueue
    from app.models import Match
    from datetime import datetime
    
    try:
        # Get pending queue entries with subscriptions
        # Note: Use naive UTC for database comparison since SQLite stores naive datetimes
        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        # Include a small buffer window so entries scheduled very recently (or set to now)
        # are still included in the UI even if the page renders a few seconds later.
        buffer_seconds = 120
        now_minus_buffer = now_utc_naive - timedelta(seconds=buffer_seconds)
        pending_queue = db.session.query(
            NotificationQueue, NotificationSubscription
        ).join(
            NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
        ).filter(
            NotificationSubscription.user_id == current_user.id,
            NotificationQueue.status == 'pending',
            NotificationQueue.scheduled_for >= now_minus_buffer
        ).order_by(NotificationQueue.scheduled_for.asc()).limit(50).all()
        
        # Join with Match data from main database
        pending_notifications = []
        for queue, subscription in pending_queue:
            match = Match.query.get(queue.match_id)
            if match:
                pending_notifications.append((queue, subscription, match))
    except Exception as e:
        print(f"Error fetching pending notifications: {e}")
        pending_notifications = []
    
    # Get VAPID public key for push notifications
    vapid_keys = get_vapid_keys()
    vapid_public_key = vapid_keys.get('public_key', '')
    
    # Get available teams at current event
    from app.utils.config_manager import get_current_game_config
    game_config = get_current_game_config()
    event_code = game_config.get('current_event_code')
    
    available_teams = []
    current_event = None
    if event_code:
        current_event = Event.query.filter_by(
            code=event_code,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        if current_event:
            available_teams = Team.query.filter(
                Team.events.contains(current_event),
                Team.scouting_team_number == current_user.scouting_team_number
            ).order_by(Team.team_number).all()
    
    return render_template(
        'notifications/index.html',
        subscriptions=subscriptions,
        devices=devices,
        history=history,
        pending_notifications=pending_notifications,
        vapid_public_key=vapid_public_key,
        available_teams=available_teams,
        event_code=event_code,
        current_event=current_event,
        next_schedule_seconds=get_seconds_until_next_schedule()
    )


@bp.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    """Create a new notification subscription"""
    try:
        data = request.get_json() if request.is_json else request.form
        
        notification_type = data.get('notification_type', 'match_strategy')
        target_team_number = data.get('target_team_number')
        event_code = data.get('event_code')
        
        # Handle both boolean and string values for email/push enabled
        email_val = data.get('email_enabled', True)
        if isinstance(email_val, bool):
            email_enabled = email_val
        else:
            email_enabled = str(email_val).lower() in ('true', '1', 'yes', 'on')
        
        push_val = data.get('push_enabled', True)
        if isinstance(push_val, bool):
            push_enabled = push_val
        else:
            push_enabled = str(push_val).lower() in ('true', '1', 'yes', 'on')
        
        minutes_before = int(data.get('minutes_before', 20))
        
        # For end-of-day summaries, team number may be irrelevant but event_code is required
        if notification_type == 'end_of_day_summary':
            if not event_code:
                return jsonify({'error': 'Event code is required for end-of-day summaries'}), 400
            # Normalize minutes_before for summaries (ignored by scheduler)
            minutes_before = 0
        else:
            if not target_team_number:
                return jsonify({'error': 'Team number is required'}), 400

        
        # Check if exact same subscription already exists (same type, team, timing, and delivery methods)
        existing = NotificationSubscription.query.filter_by(
            user_id=current_user.id,
            notification_type=notification_type,
            target_team_number=target_team_number,
            event_code=event_code,
            minutes_before=minutes_before,
            email_enabled=email_enabled,
            push_enabled=push_enabled
        ).first()
        
        if existing:
            # Reactivate if it was deactivated
            if not existing.is_active:
                existing.is_active = True
                existing.updated_at = datetime.now(timezone.utc)
                subscription = existing
            else:
                return jsonify({'error': 'This exact subscription already exists'}), 400
        else:
            # Create new subscription (allow multiple subscriptions for same team with different types/timing)
            subscription = NotificationSubscription(
                user_id=current_user.id,
                scouting_team_number=current_user.scouting_team_number,
                notification_type=notification_type,
                target_team_number=target_team_number,
                event_code=event_code,
                email_enabled=email_enabled,
                push_enabled=push_enabled,
                minutes_before=minutes_before,
                is_active=True
            )
            db.session.add(subscription)
        
        db.session.commit()
        
        # Schedule notifications for existing matches
        from app.utils.config_manager import get_current_game_config
        game_config = get_current_game_config()
        current_event_code = game_config.get('current_event_code')
        
        if current_event_code and event_code == current_event_code:
            # Find event and schedule notifications
            event = Event.query.filter_by(
                code=event_code,
                scouting_team_number=current_user.scouting_team_number
            ).first()
            
            if event:
                # Get matches with this team
                matches = Match.query.filter_by(
                    event_id=event.id
                ).all()
                
                scheduled_count = 0
                for match in matches:
                    if target_team_number in (match.red_teams + match.blue_teams):
                        count = schedule_notifications_for_match(match)
                        scheduled_count += count
                
                if scheduled_count > 0:
                    flash(f'Subscription created! {scheduled_count} notifications scheduled.', 'success')
                else:
                    flash('Subscription created! Notifications will be scheduled when matches are available.', 'success')
        else:
            flash('Subscription created successfully!', 'success')
        
        return jsonify({
            'success': True,
            'subscription': {
                'id': subscription.id,
                'team_number': subscription.target_team_number,
                'email_enabled': subscription.email_enabled,
                'push_enabled': subscription.push_enabled,
                'minutes_before': subscription.minutes_before
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/unsubscribe/<int:subscription_id>', methods=['POST', 'DELETE'])
@login_required
def unsubscribe(subscription_id):
    """Delete or deactivate a subscription"""
    subscription = NotificationSubscription.query.get_or_404(subscription_id)
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Deactivate instead of delete to preserve history
    subscription.is_active = False
    subscription.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    
    flash('Subscription removed successfully!', 'success')
    return jsonify({'success': True})


@bp.route('/register-device', methods=['POST'])
@login_required
def register_push_device():
    """Register a device for push notifications"""
    try:
        data = request.get_json()
        
        endpoint = data.get('endpoint')
        p256dh_key = data.get('keys', {}).get('p256dh')
        auth_key = data.get('keys', {}).get('auth')
        
        if not all([endpoint, p256dh_key, auth_key]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Register device
        device = register_device(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh_key=p256dh_key,
            auth_key=auth_key,
            user_agent=request.headers.get('User-Agent'),
            device_name=data.get('device_name')
        )
        
        return jsonify({
            'success': True,
            'device_id': device.id,
            'device_name': device.device_name
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/remove-device/<int:device_id>', methods=['POST', 'DELETE'])
@login_required
def remove_device(device_id):
    """Remove a registered device"""
    device = DeviceToken.query.get_or_404(device_id)
    
    # Verify ownership
    if device.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    device.is_active = False
    db.session.commit()
    
    flash('Device removed successfully!', 'success')
    return jsonify({'success': True})


@bp.route('/test-email', methods=['POST'])
@login_required
def test_email():
    """Send a test email notification with a random match prediction"""
    if not current_user.email:
        return jsonify({'error': 'No email address configured'}), 400
    
    try:
        from app.utils.config_manager import get_current_game_config
        from app.utils.notification_service import create_strategy_notification_message, format_match_description
        import random
        
        title = "Test Notification from ObsidianScout"
        message = f"""Hello {current_user.username}!

This is a test notification from the ObsidianScout notification system.

If you received this email, your email notifications are working correctly.

Team: {current_user.scouting_team_number}
Sent: {datetime.now(timezone.utc).strftime('%Y-%m-%d %I:%M %p UTC')}

"""
        
        # Try to add a random match prediction from current event
        try:
            game_config = get_current_game_config()
            current_event_code = game_config.get('current_event_code')
            
            if current_event_code:
                event = Event.query.filter_by(
                    code=current_event_code,
                    scouting_team_number=current_user.scouting_team_number
                ).first()
                
                if event:
                    # Get random match from event
                    matches = Match.query.filter_by(
                        event_id=event.id,
                        scouting_team_number=current_user.scouting_team_number
                    ).all()
                    
                    if matches:
                        random_match = random.choice(matches)
                        
                        # Pick a random team from the match
                        all_teams = random_match.red_teams + random_match.blue_teams
                        if all_teams:
                            random_team = random.choice(all_teams)
                            
                            # Generate prediction
                            try:
                                _, prediction = create_strategy_notification_message(random_match, random_team)
                                
                                message += f"\n{'='*50}\n"
                                message += "SAMPLE MATCH STRATEGY NOTIFICATION\n"
                                message += f"{'='*50}\n\n"
                                message += prediction
                            except Exception as pred_gen_error:
                                message += f"\n(Could not generate prediction: {str(pred_gen_error)})"
                        else:
                            message += "\n(No match data available for prediction demo)"
                    else:
                        message += "\n(No matches found at current event for prediction demo)"
                else:
                    message += f"\n(Event '{current_event_code}' not found for prediction demo)"
            else:
                message += "\n(No current event configured for prediction demo)"
        except Exception as pred_error:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Error generating prediction demo: {error_detail}")
            message += f"\n(Could not generate prediction demo: {str(pred_error)})"
        
        success, error = send_email(
            to=current_user.email,
            subject=title,
            body=message
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Test email sent to {current_user.email}'
            })
        else:
            return jsonify({
                'error': f'Failed to send email: {error}'
            }), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/test-push', methods=['POST'])
@login_required
def test_push():
    """Send a test push notification to all user devices"""
    try:
        # Check if user has any active devices
        device_count = DeviceToken.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).count()
        
        if device_count == 0:
            return jsonify({'error': 'No active devices registered. Please enable notifications in your browser first.'}), 400
        
        title = "Test Notification"
        message = f"Hello {current_user.username}! Your push notifications are working correctly."
        
        data = {
            'type': 'test',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        success_count, failed_count, errors = send_push_to_user(
            user_id=current_user.id,
            title=title,
            message=message,
            data=data
        )
        
        if success_count > 0:
            return jsonify({
                'success': True,
                'message': f'Test notification sent to {success_count} device(s)',
                'success_count': success_count,
                'failed_count': failed_count
            })
        else:
            error_msg = '\n'.join(errors) if errors else 'Unknown error'
            return jsonify({
                'error': f'Failed to send push notifications: {error_msg}'
            }), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/test-subscription/<int:subscription_id>', methods=['POST'])
@login_required
def test_subscription(subscription_id):
    """Send a test notification for a specific subscription"""
    subscription = NotificationSubscription.query.get_or_404(subscription_id)
    
    # Verify ownership
    if subscription.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        # Find a recent or upcoming match with this team
        from app.utils.config_manager import get_current_game_config
        game_config = get_current_game_config()
        event_code = game_config.get('current_event_code')
        
        if not event_code:
            return jsonify({'error': 'No event configured'}), 400
        
        event = Event.query.filter_by(
            code=event_code,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        if not event:
            return jsonify({'error': 'Event not found'}), 404
        
        # Find a match with this team
        matches = Match.query.filter_by(event_id=event.id).all()
        test_match = None
        
        for match in matches:
            if subscription.target_team_number in (match.red_teams + match.blue_teams):
                test_match = match
                break
        
        if not test_match:
            return jsonify({'error': f'No matches found with team {subscription.target_team_number}'}), 404
        
        # Send test notification
        log = send_notification_for_subscription(subscription, test_match)
        
        if log:
            result = {
                'success': True,
                'message': 'Test notification sent',
                'email_sent': log.email_sent,
                'push_sent_count': log.push_sent_count,
                'push_failed_count': log.push_failed_count
            }
            
            if log.email_error:
                result['email_error'] = log.email_error
            if log.push_error:
                result['push_error'] = log.push_error
            
            return jsonify(result)
        else:
            return jsonify({'error': 'Failed to send test notification'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/vapid-public-key')
def get_vapid_public_key():
    """Get VAPID public key for push subscription"""
    vapid_keys = get_vapid_keys()
    return jsonify({
        'publicKey': vapid_keys.get('public_key', '')
    })


@bp.route('/history')
@login_required
def history():
    """Get notification history for current user"""
    limit = request.args.get('limit', 50, type=int)
    history = get_user_notification_history(current_user.id, limit=limit)
    
    return jsonify({
        'history': [{
            'id': log.id,
            'type': log.notification_type,
            'title': log.title,
            'message': log.message,
            'team_number': log.team_number,
            'email_sent': log.email_sent,
            'push_sent_count': log.push_sent_count,
            'sent_at': log.sent_at.isoformat() if log.sent_at else None
        } for log in history]
    })


@bp.route('/refresh-schedule', methods=['POST'])
@login_required
def refresh_schedule():
    """Refresh notification schedule by fetching latest match times from FRC APIs"""
    try:
        from app.utils.config_manager import get_current_game_config
        from app.utils.match_time_fetcher import update_match_times
        from app.models_misc import NotificationQueue
        
        game_config = get_current_game_config()
        event_code = game_config.get('current_event_code')
        
        if not event_code:
            return jsonify({'error': 'No current event configured'}), 400
        
        # Update match times from FRC APIs (FIRST or TBA)
        updated_count = update_match_times(event_code, current_user.scouting_team_number)
        
        # Clear and reschedule all pending notifications for this event
        event = Event.query.filter_by(
            code=event_code,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        
        if not event:
            return jsonify({'error': f'Event {event_code} not found'}), 404
        
        # Get all matches for this event first (from scouting.db)
        matches = Match.query.filter_by(event_id=event.id).all()
        match_ids = [m.id for m in matches]
        
        print(f" Found {len(matches)} matches for event {event_code}")
        if matches:
            # Show some match details
            for match in matches[:5]:  # Show first 5
                print(f"  - {match.match_type} {match.match_number}: scheduled={match.scheduled_time}, predicted={match.predicted_time}")
                print(f"    Teams: Red={match.red_teams}, Blue={match.blue_teams}")
        
        # Delete old pending notifications for these matches (from misc.db)
        # Do this in Python to avoid cross-database join
        if match_ids:
            pending_queue = NotificationQueue.query.filter(
                NotificationQueue.status == 'pending'
            ).all()
            
            deleted_count = 0
            for queue_entry in pending_queue:
                if queue_entry.match_id in match_ids:
                    db.session.delete(queue_entry)
                    deleted_count += 1
            
            db.session.commit()
            print(f"Deleted {deleted_count} old pending notifications")
        
        # Reschedule notifications for all matches
        scheduled_count = 0
        
        # Show active subscriptions for debugging
        from app.models_misc import NotificationSubscription
        active_subs = NotificationSubscription.query.filter_by(
            is_active=True,
            scouting_team_number=current_user.scouting_team_number
        ).all()
        print(f"Found {len(active_subs)} active subscriptions for team {current_user.scouting_team_number}")
        for sub in active_subs:
            print(f"  - Team {sub.target_team_number}, Type: {sub.notification_type}, Minutes before: {sub.minutes_before}")
        
        for match in matches:
            count = schedule_notifications_for_match(match)
            scheduled_count += count
        
        # Fetch updated pending notifications for response
        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        buffer_seconds = 120
        now_minus_buffer = now_utc_naive - timedelta(seconds=buffer_seconds)
        pending_queue = db.session.query(
            NotificationQueue, NotificationSubscription
        ).join(
            NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
        ).filter(
            NotificationSubscription.user_id == current_user.id,
            NotificationQueue.status == 'pending',
            NotificationQueue.scheduled_for >= now_minus_buffer
        ).order_by(NotificationQueue.scheduled_for.asc()).limit(50).all()
        
        # Join with Match data from main database
        pending_list = []
        for queue, subscription in pending_queue:
            match = Match.query.get(queue.match_id)
            if match:
                # Use predicted_time if available (adjusted schedule), otherwise scheduled_time
                match_time = match.predicted_time if match.predicted_time else match.scheduled_time
                # Get event for timezone
                event = Event.query.get(match.event_id) if match.event_id else None
                pending_list.append({
                    'id': queue.id,
                    'match_type': match.match_type,
                    'match_number': match.match_number,
                    'team_number': subscription.target_team_number,
                    'scheduled_for': queue.scheduled_for.isoformat() if queue.scheduled_for else None,
                    'match_time': match_time.isoformat() if match_time else None,
                    'is_predicted': bool(match.predicted_time),
                    'notification_type': subscription.notification_type,
                    'minutes_before': subscription.minutes_before,
                    'event_timezone': event.timezone if event else None
                })
        
        return jsonify({
            'success': True,
            'message': f'Schedule refreshed! Updated {updated_count} match times, rescheduled {scheduled_count} notifications.',
            'matches_updated': updated_count,
            'notifications_scheduled': scheduled_count,
            'pending_notifications': pending_list
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/clear-scheduled', methods=['POST'])
@login_required
def clear_scheduled_notifications():
    """Clear all pending scheduled notifications that belong to the current user.

    This will remove pending NotificationQueue entries that were scheduled for
    the current user's subscriptions.
    """
    try:
        from datetime import datetime, timezone
        from app.models_misc import NotificationQueue, NotificationSubscription

        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        buffer_seconds = 120
        now_minus_buffer = now_utc_naive - timedelta(seconds=buffer_seconds)

        # Query pending queue entries that belong to this user's subscriptions
        q = db.session.query(NotificationQueue).join(
            NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
        ).filter(
            NotificationSubscription.user_id == current_user.id,
            NotificationQueue.status == 'pending',
            NotificationQueue.scheduled_for >= now_minus_buffer
        )

        to_delete = q.all()
        deleted_count = len(to_delete)

        for entry in to_delete:
            db.session.delete(entry)

        db.session.commit()

        return jsonify({'success': True, 'deleted': deleted_count, 'message': f'Cleared {deleted_count} pending scheduled notification(s).'})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing scheduled notifications for user {getattr(current_user, 'id', None)}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/clear-history', methods=['POST'])
@login_required
def clear_notification_history():
    """Clear notification queue entries and optionally notification log entries for a specific
    match and/or subscription. Optionally reschedule notifications for the given match.

    Expected JSON body:
      - match_id: (optional) integer
      - subscription_id: (optional) integer
      - include_logs: (optional) boolean (default: False) — delete NotificationLog entries
      - reschedule: (optional) boolean (default: False) — call schedule_notifications_for_match after clearing
    """
    try:
        data = request.get_json() if request.is_json else request.form
        match_id = data.get('match_id')
        subscription_id = data.get('subscription_id')
        log_id = data.get('log_id')
        include_logs = str(data.get('include_logs', 'false')).lower() in ('true', '1', 'yes', 'on')
        do_reschedule = str(data.get('reschedule', 'false')).lower() in ('true', '1', 'yes', 'on')
        clear_queue = str(data.get('clear_queue', 'false')).lower() in ('true', '1', 'yes', 'on')

        # Validate input
        if not match_id and not subscription_id:
            return jsonify({'error': 'match_id or subscription_id is required'}), 400

        from app.models_misc import NotificationQueue, NotificationLog, NotificationSubscription
        from app.models import Match, Event

        # If subscription specified, verify ownership
        if subscription_id:
            sub = NotificationSubscription.query.get_or_404(subscription_id)
            if sub.user_id != current_user.id:
                return jsonify({'error': 'Unauthorized subscription access'}), 403
        else:
            sub = None

        # If match specified, verify it belongs to the same scouting team
        match = None
        if match_id:
            match = Match.query.get(match_id)
            if not match:
                return jsonify({'error': f'Match {match_id} not found'}), 404
            # Verify match belongs to the user's scouting_team_number via event
            event = Event.query.get(match.event_id) if match.event_id else None
            if event and event.scouting_team_number != current_user.scouting_team_number:
                return jsonify({'error': 'Unauthorized match access'}), 403

        # If a log_id was provided, load and verify ownership
        log = None
        if log_id:
            log = NotificationLog.query.get(log_id)
            if not log:
                return jsonify({'error': f'Log {log_id} not found'}), 404
            if log.user_id != current_user.id:
                return jsonify({'error': 'Unauthorized log access'}), 403
            # If log references a match/subscription and they weren't provided explicitly, use them
            if not match_id and log.match_id:
                match_id = log.match_id
                match = Match.query.get(match_id)
            if not subscription_id and log.subscription_id:
                subscription_id = log.subscription_id

        # Build query to delete NotificationQueue entries
        q = NotificationQueue.query
        if match_id:
            q = q.filter(NotificationQueue.match_id == match_id)
        if subscription_id:
            q = q.filter(NotificationQueue.subscription_id == subscription_id)

        # Limit to entries that belong to this user's subscriptions unless a specific subscription was provided
        if not subscription_id:
            # Join to subscription to ensure only this user's subscriptions
            q = q.join(NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id)
            q = q.filter(NotificationSubscription.user_id == current_user.id)

        to_delete_queue = q.all()
        deleted_queue_count = len(to_delete_queue)

        for entry in to_delete_queue:
            db.session.delete(entry)

        deleted_logs_count = 0
        if include_logs:
            # Delete related NotificationLog entries
            lq = NotificationLog.query
            if match_id:
                lq = lq.filter(NotificationLog.match_id == match_id)
            if subscription_id:
                lq = lq.filter(NotificationLog.subscription_id == subscription_id)
            if not subscription_id:
                # Only the current user's logs: join via subscription
                lq = lq.join(NotificationSubscription, NotificationLog.subscription_id == NotificationSubscription.id)
                lq = lq.filter(NotificationSubscription.user_id == current_user.id)

            logs_to_delete = lq.all()
            deleted_logs_count = len(logs_to_delete)
            for lg in logs_to_delete:
                db.session.delete(lg)

        # If a specific log_id was provided, delete that single log (unless include_logs handled it)
        if log_id and not include_logs:
            try:
                db.session.delete(log)
                deleted_logs_count += 1
            except Exception:
                pass

        db.session.commit()

        scheduled_count = 0
        if do_reschedule and match:
            # Re-run scheduling for this match (will only create pending entries)
            scheduled_count = schedule_notifications_for_match(match)

        # If requested, clear related queue entries by log reference (used when calling by log_id)
        if log_id and clear_queue and match:
            try:
                q2 = NotificationQueue.query.filter(NotificationQueue.match_id == match.id)
                if subscription_id:
                    q2 = q2.filter(NotificationQueue.subscription_id == subscription_id)
                # Ensure queue entries belong to this user's subscriptions
                q2 = q2.join(NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id)
                q2 = q2.filter(NotificationSubscription.user_id == current_user.id)
                q_entries = q2.all()
                for qe in q_entries:
                    db.session.delete(qe)
                    deleted_queue_count += 1
                db.session.commit()
            except Exception:
                db.session.rollback()

        return jsonify({
            'success': True,
            'deleted_queue': deleted_queue_count,
            'deleted_logs': deleted_logs_count,
            'rescheduled': scheduled_count,
            'message': f'Cleared {deleted_queue_count} queue entries and {deleted_logs_count} logs.'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing notification history: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/clear-all-history', methods=['POST'])
@login_required
def clear_all_history():
    """Delete all NotificationLog rows that belong to the current user.

    This is a destructive action and should be confirmed on the client.
    Returns the number of deleted rows.
    """
    try:
        from app.models_misc import NotificationLog

        # Bulk delete logs for this user
        deleted = NotificationLog.query.filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.commit()

        return jsonify({'success': True, 'deleted_logs': deleted, 'message': f'Deleted {deleted} log(s) for your account.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing all notification history for user {getattr(current_user,'id',None)}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/mobile-schedule', methods=['GET'])
@login_required
def mobile_schedule_ui():
    """UI page to create test scheduled and past notifications for mobile API testing."""
    # Gather user's subscriptions and recent matches for current event
    subs = NotificationSubscription.query.filter_by(user_id=current_user.id).order_by(NotificationSubscription.created_at.desc()).all()

    # Try to find current event and matches
    from app.utils.config_manager import get_current_game_config
    game_config = get_current_game_config()
    event_code = game_config.get('current_event_code')

    matches = []
    current_event = None
    if event_code:
        current_event = Event.query.filter_by(code=event_code, scouting_team_number=current_user.scouting_team_number).first()
        if current_event:
            matches = Match.query.filter_by(event_id=current_event.id, scouting_team_number=current_user.scouting_team_number).order_by(Match.match_number).all()

    return render_template('notifications/mobile_schedule.html', subscriptions=subs, matches=matches, event_code=event_code)


@bp.route('/mobile-schedule/create', methods=['POST'])
@login_required
def mobile_schedule_create():
    """Create a scheduled NotificationQueue entry for testing.

    Expected JSON fields:
      - subscription_id (optional) OR subscription (object with fields to create subscription)
      - match_id (required)
      - scheduled_for (ISO 8601 datetime string, interpreted as local time in the browser and converted to UTC by client)
    """
    try:
        data = request.get_json() or {}
        subscription_id = data.get('subscription_id')
        match_id = data.get('match_id')
        scheduled_for = data.get('scheduled_for')

        if not match_id or not scheduled_for:
            return jsonify({'success': False, 'error': 'match_id and scheduled_for are required'}), 400

        # If subscription_id missing, create a subscription from provided object
        if not subscription_id:
            sub_data = data.get('subscription') or {}
            if not sub_data.get('notification_type') or not sub_data.get('target_team_number'):
                return jsonify({'success': False, 'error': 'Either subscription_id or subscription object with notification_type and target_team_number is required'}), 400

            subscription = NotificationSubscription(
                user_id=current_user.id,
                scouting_team_number=current_user.scouting_team_number,
                notification_type=sub_data.get('notification_type'),
                target_team_number=int(sub_data.get('target_team_number')),
                event_code=sub_data.get('event_code'),
                email_enabled=bool(sub_data.get('email_enabled', True)),
                push_enabled=bool(sub_data.get('push_enabled', True)),
                minutes_before=int(sub_data.get('minutes_before', 20)),
                is_active=True
            )
            db.session.add(subscription)
            db.session.flush()  # get id
            subscription_id = subscription.id

        # Parse scheduled_for (client sends ISO in UTC)
        from datetime import datetime, timezone
        try:
            sched_dt = datetime.fromisoformat(scheduled_for)
            # Ensure naive UTC stored in NotificationQueue to match existing behavior
            sched_dt = sched_dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid scheduled_for datetime format'}), 400

        # Create queue entry
        from app.models_misc import NotificationQueue
        queue_entry = NotificationQueue(
            subscription_id=subscription_id,
            match_id=int(match_id),
            scheduled_for=sched_dt,
            status='pending',
            attempts=0
        )
        db.session.add(queue_entry)
        db.session.commit()

        return jsonify({'success': True, 'queue_id': queue_entry.id})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating mobile schedule entry: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/mobile-schedule/create-past', methods=['POST'])
@login_required
def mobile_schedule_create_past():
    """Create a past NotificationLog entry for testing.

    Expected JSON fields:
      - notification_type (required)
      - title
      - message
      - match_id (optional)
      - event_code (optional)
      - team_number (optional)
      - email_sent (bool)
      - push_sent_count (int)
      - sent_at (ISO datetime string) -- if omitted, now is used
    """
    try:
        data = request.get_json() or {}
        notif_type = data.get('notification_type')
        if not notif_type:
            return jsonify({'success': False, 'error': 'notification_type is required'}), 400

        title = data.get('title') or f'Test {notif_type}'
        message = data.get('message') or ''
        match_id = data.get('match_id')
        event_code = data.get('event_code')
        team_number = data.get('team_number')
        email_sent = bool(data.get('email_sent', False))
        push_sent_count = int(data.get('push_sent_count', 0) or 0)
        email_error = data.get('email_error')
        push_error = data.get('push_error')

        from datetime import datetime, timezone
        sent_at_raw = data.get('sent_at')
        if sent_at_raw:
            try:
                sent_at = datetime.fromisoformat(sent_at_raw).astimezone(timezone.utc)
            except Exception:
                return jsonify({'success': False, 'error': 'Invalid sent_at format'}), 400
        else:
            sent_at = datetime.now(timezone.utc)

        # Create log
        log = NotificationLog(
            user_id=current_user.id,
            subscription_id=data.get('subscription_id'),
            notification_type=notif_type,
            title=title,
            message=message,
            match_id=match_id,
            team_number=team_number,
            event_code=event_code,
            email_sent=email_sent,
            email_error=email_error,
            push_sent_count=push_sent_count,
            push_error=push_error,
            sent_at=sent_at
        )
        db.session.add(log)
        db.session.commit()

        return jsonify({'success': True, 'log_id': log.id})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating past notification log: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
