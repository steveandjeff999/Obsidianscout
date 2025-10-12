"""
Notification Scheduler and Sender Service
Handles scheduling and sending notifications for matches and events
"""
from datetime import datetime, timedelta
from flask import current_app
from app import db
from app.models import Match, Team, Event, User
from app.models_misc import NotificationSubscription, NotificationLog, NotificationQueue, DeviceToken
from app.utils.emailer import send_email, _build_html_email
from app.utils.push_notifications import send_push_to_user
import traceback


def get_match_time(match):
    """Get the best available time for a match (scheduled or predicted)"""
    if match.scheduled_time:
        return match.scheduled_time
    elif match.predicted_time:
        return match.predicted_time
    return None


def format_match_description(match):
    """Format a human-readable match description"""
    red_teams = ', '.join([str(t) for t in match.red_teams])
    blue_teams = ', '.join([str(t) for t in match.blue_teams])
    return f"{match.match_type} {match.match_number}: Red({red_teams}) vs Blue({blue_teams})"


def get_team_performance_stats(team_id, scouting_team_number):
    """
    Calculate performance statistics for a team from scouting data.
    Returns dict with auto_avg, teleop_avg, total_avg, match_count
    """
    from app.models import ScoutingData
    
    team_data = ScoutingData.query.filter_by(
        team_id=team_id,
        scouting_team_number=scouting_team_number
    ).all()
    
    if not team_data:
        return None
    
    # Try to calculate metrics using the calculate_metric method
    auto_scores = []
    teleop_scores = []
    total_scores = []
    
    for entry in team_data:
        try:
            # Try standard metric IDs first
            auto = entry.calculate_metric('apt')  # Auto Points Total
            if auto is not None:
                auto_scores.append(float(auto))
        except:
            pass
        
        try:
            teleop = entry.calculate_metric('tpt')  # Teleop Points Total
            if teleop is not None:
                teleop_scores.append(float(teleop))
        except:
            pass
        
        try:
            total = entry.calculate_metric('tot')  # Total Points
            if total is not None:
                total_scores.append(float(total))
        except:
            pass
    
    # If we got scores, calculate averages
    if total_scores:
        return {
            'auto_avg': sum(auto_scores) / len(auto_scores) if auto_scores else 0,
            'teleop_avg': sum(teleop_scores) / len(teleop_scores) if teleop_scores else 0,
            'total_avg': sum(total_scores) / len(total_scores),
            'match_count': len(team_data)
        }
    
    # Fallback: Try to sum numeric values from data_json
    # This is a rough estimate when metrics aren't configured
    fallback_totals = []
    for entry in team_data:
        try:
            data = entry.data
            total = 0
            for key, value in data.items():
                if isinstance(value, (int, float)) and value > 0:
                    total += value
            if total > 0:
                fallback_totals.append(total)
        except:
            pass
    
    if fallback_totals:
        avg = sum(fallback_totals) / len(fallback_totals)
        return {
            'auto_avg': avg * 0.33,  # Rough estimate: 33% auto
            'teleop_avg': avg * 0.67,  # Rough estimate: 67% teleop
            'total_avg': avg,
            'match_count': len(team_data)
        }
    
    return None


def create_match_prediction_html(match, target_team_number, message):
    """
    Generate styled HTML content for match strategy email
    
    Args:
        match: Match model instance
        target_team_number: Team number being tracked
        message: Plain text message to format
        
    Returns:
        HTML string with styled match prediction
    """
    from app.models import Team, Event
    
    # Get match details
    match_number = f"#{match.match_number}" if match.match_number else ""
    match_type = match.match_type or "Match"
    
    # Get event info
    event = Event.query.get(match.event_id) if match.event_id else None
    event_name = event.name if event else "Unknown Event"
    event_code = event.code if event else ""
    
    # Get scheduled time
    scheduled_time = ""
    if match.scheduled_time:
        try:
            scheduled_time = match.scheduled_time.strftime("%I:%M %p")
        except:
            scheduled_time = str(match.scheduled_time)
    
    # Parse the message to extract team stats
    # Message format: "Match X is coming up...\n\nTeam XXXX:\nAuto: X pts...\n\nAlliance Partners:\nTeam XXXX..."
    message_parts = message.split('\n\n')
    
    # Build HTML with styled sections
    html_content = f"""
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 24px; border-radius: 8px; margin-bottom: 20px;">
        <h2 style="margin: 0 0 8px 0; color: #ffffff; font-size: 24px; font-weight: 700;">
            🏆 {match_type} {match_number} Strategy
        </h2>
        <div style="color: rgba(255, 255, 255, 0.95); font-size: 16px; font-weight: 500;">
            Team {target_team_number} Upcoming Match
        </div>
        {f'<div style="color: rgba(255, 255, 255, 0.85); font-size: 14px; margin-top: 8px;">⏰ Scheduled: {scheduled_time}</div>' if scheduled_time else ''}
    </div>
    
    <div style="background: #f8f9fa; padding: 16px; border-left: 4px solid #667eea; border-radius: 4px; margin-bottom: 20px;">
        <div style="font-size: 14px; color: #555; font-weight: 600; margin-bottom: 8px;">📍 Event</div>
        <div style="font-size: 16px; color: #333; font-weight: 500;">{event_name}</div>
        {f'<div style="font-size: 13px; color: #666; margin-top: 4px;">{event_code}</div>' if event_code else ''}
    </div>
    """
    
    # Process message sections
    for part in message_parts:
        part = part.strip()
        if not part:
            continue
            
        # Team performance section
        if part.startswith('Team ') and (':' in part or 'Auto:' in part or 'Teleop:' in part):
            lines = part.split('\n')
            team_line = lines[0]
            stats_lines = lines[1:] if len(lines) > 1 else []
            
            # Extract team number from first line
            team_num = ''
            for word in team_line.split():
                if word.replace(':', '').isdigit():
                    team_num = word.replace(':', '')
                    break
            
            # Determine if this is the target team or alliance partner
            is_target = team_num == str(target_team_number)
            bg_color = '#e8f5e9' if is_target else '#fff3e0'
            border_color = '#4caf50' if is_target else '#ff9800'
            icon = '⭐' if is_target else '🤝'
            
            html_content += f"""
    <div style="background: {bg_color}; padding: 18px; border-left: 4px solid {border_color}; border-radius: 6px; margin-bottom: 16px;">
        <div style="font-size: 18px; color: #333; font-weight: 700; margin-bottom: 12px;">
            {icon} {team_line}
        </div>
        <table style="width: 100%; border-collapse: collapse;">
"""
            
            for stat_line in stats_lines:
                stat_line = stat_line.strip()
                if ':' in stat_line:
                    label, value = stat_line.split(':', 1)
                    label = label.strip()
                    value = value.strip()
                    
                    # Add emoji icons for different stats
                    stat_icon = ''
                    if 'Auto' in label or 'Autonomous' in label:
                        stat_icon = '🤖'
                    elif 'Teleop' in label or 'TeleOp' in label:
                        stat_icon = '🎮'
                    elif 'Total' in label or 'Overall' in label:
                        stat_icon = '📊'
                    elif 'matches' in label.lower():
                        stat_icon = '🔢'
                    
                    html_content += f"""
            <tr>
                <td style="padding: 6px 12px 6px 0; font-size: 14px; color: #666; font-weight: 600;">
                    {stat_icon} {label}:
                </td>
                <td style="padding: 6px 0; font-size: 16px; color: #333; font-weight: 700; text-align: right;">
                    {value}
                </td>
            </tr>
"""
            
            html_content += """
        </table>
    </div>
"""
        
        # Alliance Partners section header
        elif 'Alliance Partners' in part or 'alliance partners' in part.lower():
            html_content += f"""
    <div style="margin: 24px 0 16px 0;">
        <h3 style="margin: 0; color: #444; font-size: 18px; font-weight: 700; border-bottom: 2px solid #ff9800; padding-bottom: 8px;">
            🤝 Alliance Partners
        </h3>
    </div>
"""
        
        # General text sections
        elif not part.startswith('Team '):
            html_content += f"""
    <div style="padding: 12px 0; font-size: 14px; color: #555; line-height: 1.6;">
        {part.replace(chr(10), '<br>')}
    </div>
"""
    
    # Add action button
    match_url = f"/matches/{match.id}"
    html_content += f"""
    <div style="text-align: center; margin-top: 28px; padding-top: 20px; border-top: 2px solid #e0e0e0;">
        <a href="{match_url}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 6px; font-weight: 600; font-size: 15px; box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);">
            📋 View Full Match Details
        </a>
    </div>
    
    <div style="margin-top: 24px; padding: 16px; background: #f0f4ff; border-radius: 6px; text-align: center;">
        <div style="font-size: 13px; color: #666; line-height: 1.5;">
            💡 <strong>Pro Tip:</strong> Review your alliance partners' strengths and coordinate your strategy before the match!
        </div>
    </div>
"""
    
    return html_content


def create_strategy_notification_message(match, target_team_number):
    """Create notification message for match strategy reminder with predictions"""
    from app.models import ScoutingData
    
    # Determine if target team is on red or blue alliance
    alliance_color = None
    if target_team_number in match.red_teams:
        alliance_color = 'Red'
        alliance_teams = match.red_teams
        opponent_teams = match.blue_teams
    elif target_team_number in match.blue_teams:
        alliance_color = 'Blue'
        alliance_teams = match.blue_teams
        opponent_teams = match.red_teams
    else:
        alliance_color = 'Unknown'
        alliance_teams = []
        opponent_teams = []
    
    title = f"Match Strategy: Team {target_team_number}"
    
    message = f"Match {match.match_type} {match.match_number} starting soon!\n\n"
    message += f"Team {target_team_number} is on {alliance_color} Alliance\n"
    
    if alliance_teams:
        message += f"{alliance_color} Alliance: {', '.join([str(t) for t in alliance_teams])}\n"
    if opponent_teams:
        opponent_color = 'Blue' if alliance_color == 'Red' else 'Red'
        message += f"{opponent_color} Alliance: {', '.join([str(t) for t in opponent_teams])}\n"
    
    match_time = get_match_time(match)
    if match_time:
        message += f"\nScheduled: {match_time.strftime('%I:%M %p')}\n"
    
    # Add match predictions based on scouting data
    message += "\n--- MATCH ANALYSIS ---\n"
    
    # Get average scores for alliance teams
    if alliance_teams:
        message += f"\n{alliance_color} Alliance Analysis:\n"
        for team_num in alliance_teams:
            # Get team by team_number
            team = Team.query.filter_by(
                team_number=team_num,
                scouting_team_number=match.scouting_team_number
            ).first()
            
            if team:
                stats = get_team_performance_stats(team.id, match.scouting_team_number)
                
                if stats:
                    message += f"  Team {team_num}: ~{stats['total_avg']:.1f} pts/match "
                    message += f"(Auto: {stats['auto_avg']:.1f}, Teleop: {stats['teleop_avg']:.1f}) "
                    message += f"[{stats['match_count']} matches]\n"
                else:
                    message += f"  Team {team_num}: No scouting data available\n"
            else:
                message += f"  Team {team_num}: Team not found in database\n"
    
    if opponent_teams:
        opponent_color = 'Blue' if alliance_color == 'Red' else 'Red'
        message += f"\n{opponent_color} Alliance Analysis:\n"
        for team_num in opponent_teams:
            # Get team by team_number
            team = Team.query.filter_by(
                team_number=team_num,
                scouting_team_number=match.scouting_team_number
            ).first()
            
            if team:
                stats = get_team_performance_stats(team.id, match.scouting_team_number)
                
                if stats:
                    message += f"  Team {team_num}: ~{stats['total_avg']:.1f} pts/match "
                    message += f"(Auto: {stats['auto_avg']:.1f}, Teleop: {stats['teleop_avg']:.1f}) "
                    message += f"[{stats['match_count']} matches]\n"
                else:
                    message += f"  Team {team_num}: No scouting data available\n"
            else:
                message += f"  Team {team_num}: Team not found in database\n"
    
    # Calculate predicted outcome
    alliance_avg = 0
    opponent_avg = 0
    alliance_count = 0
    opponent_count = 0
    
    for team_num in alliance_teams:
        team = Team.query.filter_by(
            team_number=team_num,
            scouting_team_number=match.scouting_team_number
        ).first()
        
        if team:
            stats = get_team_performance_stats(team.id, match.scouting_team_number)
            if stats:
                alliance_avg += stats['total_avg']
                alliance_count += 1
    
    for team_num in opponent_teams:
        team = Team.query.filter_by(
            team_number=team_num,
            scouting_team_number=match.scouting_team_number
        ).first()
        
        if team:
            stats = get_team_performance_stats(team.id, match.scouting_team_number)
            if stats:
                opponent_avg += stats['total_avg']
                opponent_count += 1
    
    if alliance_count > 0 and opponent_count > 0:
        opponent_color = 'Blue' if alliance_color == 'Red' else 'Red'
        message += f"\nPredicted Score:\n"
        message += f"  {alliance_color}: {alliance_avg:.0f} points\n"
        message += f"  {opponent_color}: {opponent_avg:.0f} points\n"
        
        if alliance_avg > opponent_avg:
            message += f"\n🎯 Prediction: {alliance_color} Alliance wins by {(alliance_avg - opponent_avg):.0f} points\n"
        elif opponent_avg > alliance_avg:
            message += f"\n🎯 Prediction: {opponent_color} Alliance wins by {(opponent_avg - alliance_avg):.0f} points\n"
        else:
            message += f"\n🎯 Prediction: Close match - too close to call!\n"
    
    return title, message


def send_notification_for_subscription(subscription, match):
    """
    Send notification (email and/or push) for a specific subscription and match
    
    Returns:
        NotificationLog instance
    """
    try:
        # Get user
        user = User.query.get(subscription.user_id)
        if not user:
            print(f"User {subscription.user_id} not found for subscription {subscription.id}")
            return None
        
        # Create notification message based on type
        if subscription.notification_type == 'match_strategy':
            title, message = create_strategy_notification_message(match, subscription.target_team_number)
        else:
            # Generic match reminder
            title = f"Match Reminder"
            message = f"Match starting in {subscription.minutes_before} minutes!\n\n{format_match_description(match)}"
        
        # Create log entry
        log = NotificationLog(
            user_id=user.id,
            subscription_id=subscription.id,
            notification_type=subscription.notification_type,
            title=title,
            message=message,
            match_id=match.id,
            team_number=subscription.target_team_number,
            event_code=subscription.event_code,
            sent_at=datetime.utcnow()
        )
        
        # Send email if enabled
        if subscription.email_enabled and user.email:
            try:
                # Generate styled HTML email content
                html_content_inner = create_match_prediction_html(match, subscription.target_team_number, message)
                
                # Wrap in the email template
                brand = current_app.config.get('APP_NAME') or 'ObsidianScout'
                html_full = f"""
<!doctype html>
<html>
    <head>
        <meta charset="utf-8"> 
        <meta name="viewport" content="width=device-width,initial-scale=1"> 
        <title>{title}</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background:#f6f7fb; margin:0; padding:20px;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e6e9ef;">
            <div style="padding:18px 24px;background:linear-gradient(90deg,#1f2937,#374151);color:#fff">
                <h1 style="margin:0;font-size:18px;font-weight:600;">{brand}</h1>
                <div style="font-size:13px;opacity:0.9">{title}</div>
            </div>
            <div style="padding:20px 24px;color:#111;">
                {html_content_inner}
            </div>
            <div style="padding:12px 24px;background:#fafafa;border-top:1px solid #f0f0f3;font-size:12px;color:#666;">
                <div>From: {current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@obsidianscout.app')}</div>
                <div style="margin-top:6px;color:#999;font-size:11px">This is an automated notification from ObsidianScout</div>
            </div>
        </div>
    </body>
</html>
"""
                
                # Also create plain text version (keep message as is for plain text fallback)
                event = Event.query.get(match.event_id) if match.event_id else None
                email_body = message
                if event:
                    email_body += f"\n\nEvent: {event.name} ({event.code})"
                email_body += f"\n\nView match details: {current_app.config.get('SERVER_URL', 'http://localhost:8080')}/matches/{match.id}"
                
                # Send with HTML version
                success, error = send_email(
                    to=user.email,
                    subject=title,
                    body=email_body,
                    html=html_full
                )
                
                if success:
                    log.email_sent = True
                    print(f"✅ Email sent to {user.email} for match {match.id}")
                else:
                    log.email_error = error
                    print(f"❌ Email failed for {user.email}: {error}")
            except Exception as e:
                import traceback
                log.email_error = str(e)
                print(f"❌ Email exception for {user.email}: {e}")
                traceback.print_exc()
        
        # Send push notification if enabled
        if subscription.push_enabled:
            try:
                # Check if user has any active devices
                device_count = DeviceToken.query.filter_by(
                    user_id=user.id,
                    is_active=True
                ).count()
                
                if device_count > 0:
                    # Prepare push data
                    push_data = {
                        'type': 'match_notification',
                        'match_id': match.id,
                        'team_number': subscription.target_team_number,
                        'url': f'/matches/{match.id}'
                    }
                    
                    # Truncate message if too long for push notification (max 4096 bytes for payload)
                    push_message = message
                    if len(message) > 500:  # Conservative limit for push message
                        push_message = message[:497] + "..."
                    
                    try:
                        success_count, failed_count, errors = send_push_to_user(
                            user_id=user.id,
                            title=title,
                            message=push_message,
                            data=push_data
                        )
                        
                        log.push_sent_count = success_count
                        log.push_failed_count = failed_count
                        if errors:
                            # Truncate error messages to prevent database overflow
                            error_text = '\n'.join(errors)
                            if len(error_text) > 1000:
                                error_text = error_text[:997] + "..."
                            log.push_error = error_text
                        
                        print(f"✅ Push sent to {success_count} devices for user {user.username}")
                        if failed_count > 0:
                            print(f"❌ Push failed for {failed_count} devices")
                            for err in errors:
                                print(f"   - {err}")
                    except Exception as push_ex:
                        import traceback
                        error_msg = f"Push send error: {type(push_ex).__name__}: {str(push_ex)}"
                        log.push_error = error_msg[:1000]  # Truncate for database
                        log.push_failed_count = device_count
                        print(f"❌ Push exception for user {user.username}: {push_ex}")
                        traceback.print_exc()
                else:
                    log.push_error = "No active devices registered"
                    print(f"⚠️  No active devices for user {user.username}")
            except Exception as e:
                import traceback
                log.push_error = f"Push setup error: {type(e).__name__}: {str(e)}"[:1000]
                print(f"❌ Push exception for user {user.username}: {e}")
                traceback.print_exc()
        
        # Save log
        db.session.add(log)
        db.session.commit()
        
        return log
        
    except Exception as e:
        print(f"❌ Error sending notification for subscription {subscription.id}: {e}")
        traceback.print_exc()
        db.session.rollback()
        return None


def schedule_notifications_for_match(match):
    """
    Schedule notifications for a match based on active subscriptions
    
    Returns:
        Number of notifications scheduled
    """
    # Always use latest match times from FRC APIs (FIRST or TBA)
    # Fallback to predicted times if scheduled times are missing
    # See: https://frc-api-docs.firstinspires.org/ and https://www.thebluealliance.com/apidocs/v3
    match_time = get_match_time(match)
    if not match_time:
        print(f"⚠️  Match {match.id} has no scheduled/predicted time, skipping notification scheduling")
        return 0
    
    # Get all teams in this match
    all_teams = match.red_teams + match.blue_teams
    
    # Find active subscriptions for these teams
    subscriptions = NotificationSubscription.query.filter(
        NotificationSubscription.is_active == True,
        NotificationSubscription.target_team_number.in_(all_teams),
        NotificationSubscription.scouting_team_number == match.scouting_team_number
    ).all()
    
    scheduled_count = 0
    
    for subscription in subscriptions:
        # Calculate when to send notification
        send_time = match_time - timedelta(minutes=subscription.minutes_before)
        
        # Don't schedule if already past
        if send_time < datetime.utcnow():
            continue
        
        # Check if already scheduled
        existing = NotificationQueue.query.filter_by(
            subscription_id=subscription.id,
            match_id=match.id,
            status='pending'
        ).first()
        
        if existing:
            # Update scheduled time if changed
            if existing.scheduled_for != send_time:
                existing.scheduled_for = send_time
                existing.updated_at = datetime.utcnow()
        else:
            # Create new queue entry
            queue_entry = NotificationQueue(
                subscription_id=subscription.id,
                match_id=match.id,
                scheduled_for=send_time,
                status='pending'
            )
            db.session.add(queue_entry)
            scheduled_count += 1
    
    db.session.commit()
    return scheduled_count


def process_pending_notifications():
    """
    Process all pending notifications that are due to be sent
    
    Returns:
        (sent_count, failed_count)
    """
    now = datetime.utcnow()
    
    # Get all pending notifications that are due
    pending = NotificationQueue.query.filter(
        NotificationQueue.status == 'pending',
        NotificationQueue.scheduled_for <= now,
        NotificationQueue.attempts < 3  # Max 3 attempts
    ).all()
    
    sent_count = 0
    failed_count = 0
    
    for queue_entry in pending:
        try:
            # Get subscription and match
            subscription = NotificationSubscription.query.get(queue_entry.subscription_id)
            match = Match.query.get(queue_entry.match_id)
            
            if not subscription or not match:
                queue_entry.status = 'failed'
                queue_entry.error_message = 'Subscription or match not found'
                failed_count += 1
                continue
            
            # Check if subscription is still active
            if not subscription.is_active:
                queue_entry.status = 'cancelled'
                queue_entry.error_message = 'Subscription no longer active'
                continue
            
            # Send notification
            log = send_notification_for_subscription(subscription, match)
            
            if log:
                # Check if at least one delivery method succeeded
                if log.email_sent or log.push_sent_count > 0:
                    queue_entry.status = 'sent'
                    queue_entry.last_attempt = now
                    sent_count += 1
                else:
                    # Both failed, increment attempts
                    queue_entry.attempts += 1
                    queue_entry.last_attempt = now
                    queue_entry.error_message = f"Email: {log.email_error or 'N/A'}, Push: {log.push_error or 'N/A'}"
                    
                    if queue_entry.attempts >= 3:
                        queue_entry.status = 'failed'
                        failed_count += 1
            else:
                # Notification send completely failed
                queue_entry.attempts += 1
                queue_entry.last_attempt = now
                queue_entry.error_message = 'Failed to create notification'
                
                if queue_entry.attempts >= 3:
                    queue_entry.status = 'failed'
                    failed_count += 1
                    
        except Exception as e:
            print(f"❌ Error processing notification queue {queue_entry.id}: {e}")
            traceback.print_exc()
            queue_entry.attempts += 1
            queue_entry.last_attempt = now
            queue_entry.error_message = str(e)
            
            if queue_entry.attempts >= 3:
                queue_entry.status = 'failed'
                failed_count += 1
    
    db.session.commit()
    return sent_count, failed_count


def cleanup_old_queue_entries(days=7):
    """Remove old queue entries to keep database clean"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    deleted = NotificationQueue.query.filter(
        NotificationQueue.created_at < cutoff,
        NotificationQueue.status.in_(['sent', 'failed', 'cancelled'])
    ).delete()
    
    db.session.commit()
    return deleted


def get_user_notification_history(user_id, limit=50):
    """Get recent notification history for a user"""
    return NotificationLog.query.filter_by(
        user_id=user_id
    ).order_by(
        NotificationLog.sent_at.desc()
    ).limit(limit).all()
