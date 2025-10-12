"""
Notifications Routes
Handles notification subscriptions, device registration, and testing
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
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
from datetime import datetime, timedelta

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
    
    # Get pending notifications (scheduled to send in the future)
    # Note: Match data is in different database, so we fetch separately and join in Python
    from app.models_misc import NotificationQueue
    from app.models import Match
    from datetime import datetime
    
    try:
        # Get pending queue entries with subscriptions
        pending_queue = db.session.query(
            NotificationQueue, NotificationSubscription
        ).join(
            NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
        ).filter(
            NotificationSubscription.user_id == current_user.id,
            NotificationQueue.status == 'pending',
            NotificationQueue.scheduled_for > datetime.utcnow()
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
    if event_code:
        event = Event.query.filter_by(
            code=event_code,
            scouting_team_number=current_user.scouting_team_number
        ).first()
        if event:
            available_teams = Team.query.filter(
                Team.events.contains(event),
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
        event_code=event_code
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
        
        if not target_team_number:
            return jsonify({'error': 'Team number is required'}), 400
        
        # Check if subscription already exists
        existing = NotificationSubscription.query.filter_by(
            user_id=current_user.id,
            notification_type=notification_type,
            target_team_number=target_team_number,
            event_code=event_code
        ).first()
        
        if existing:
            # Update existing subscription
            existing.email_enabled = email_enabled
            existing.push_enabled = push_enabled
            existing.minutes_before = minutes_before
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            subscription = existing
        else:
            # Create new subscription
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
    subscription.updated_at = datetime.utcnow()
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
Sent: {datetime.utcnow().strftime('%Y-%m-%d %I:%M %p UTC')}

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
            'timestamp': datetime.utcnow().isoformat()
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
        for match in matches:
            count = schedule_notifications_for_match(match)
            scheduled_count += count
        
        return jsonify({
            'success': True,
            'message': f'Schedule refreshed! Updated {updated_count} match times, rescheduled {scheduled_count} notifications.',
            'matches_updated': updated_count,
            'notifications_scheduled': scheduled_count
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
