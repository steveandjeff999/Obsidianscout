"""
Schedule Adjuster
Detects when events are running behind or ahead of schedule and adjusts match time predictions
Ensures notifications are sent at the correct time based on the actual event pace
"""
from datetime import datetime, timezone, timedelta
from flask import current_app
from app import db
from app.models import Match, Event
from app.utils.timezone_utils import convert_utc_to_local, format_time_with_timezone
from app.utils.api_utils import get_api_headers, get_preferred_api_source
from app.utils.config_manager import get_current_game_config
import requests


def fetch_actual_times_from_first(event_code, event_timezone=None):
    """
    Fetch actual match times from FIRST API
    Returns dict mapping (match_type, match_number) -> (scheduled_time, actual_time)
    """
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    headers = get_api_headers()
    
    match_times = {}
    
    # FIRST API endpoints for different match types
    endpoints = [
        (f"/v2.0/{season}/schedule/{event_code}/qual", 'Qualification'),
        (f"/v2.0/{season}/schedule/{event_code}/playoff", 'Playoff'),
        (f"/v2.0/{season}/schedule/{event_code}/practice", 'Practice'),
    ]
    
    for endpoint, match_type in endpoints:
        try:
            api_url = f"{base_url}{endpoint}"
            response = requests.get(api_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                matches = data.get('Schedule', [])
                
                for match_data in matches:
                    match_num = str(match_data.get('matchNumber'))
                    scheduled_time_str = match_data.get('startTime')
                    actual_time_str = match_data.get('actualStartTime')  # FIRST API actual time field
                    
                    scheduled = None
                    actual = None
                    
                    if scheduled_time_str:
                        try:
                            from app.utils.timezone_utils import parse_iso_with_timezone
                            scheduled = parse_iso_with_timezone(scheduled_time_str, event_timezone)
                        except Exception as e:
                            print(f"Error parsing scheduled time '{scheduled_time_str}': {e}")
                    
                    if actual_time_str:
                        try:
                            from app.utils.timezone_utils import parse_iso_with_timezone
                            actual = parse_iso_with_timezone(actual_time_str, event_timezone)
                        except Exception as e:
                            print(f"Error parsing actual time '{actual_time_str}': {e}")
                    
                    if scheduled or actual:
                        match_times[(match_type, match_num)] = (scheduled, actual)
                
        except Exception as e:
            print(f"❌ Error fetching from FIRST API {endpoint}: {e}")
    
    return match_times


def fetch_actual_times_from_tba(event_code, event_timezone=None):
    """
    Fetch actual match times from TBA API
    Returns dict mapping (match_type, match_number) -> (scheduled_time, actual_time)
    """
    from app.utils.tba_api_utils import get_tba_api_headers, construct_tba_event_key
    
    base_url = 'https://www.thebluealliance.com/api/v3'
    year = get_current_game_config().get('season', 2026)
    event_key = construct_tba_event_key(event_code, year)
    
    match_times = {}
    
    # Map TBA comp_level to our match_type (same as in match_time_fetcher and tba_api_utils)
    comp_level_map = {
        'qm': 'Qualification',
        'ef': 'Elimination',
        'qf': 'Quarterfinals',
        'sf': 'Semifinals',
        'f': 'Finals',
        'pr': 'Practice'
    }
    
    try:
        api_url = f"{base_url}/event/{event_key}/matches"
        response = requests.get(api_url, headers=get_tba_api_headers(), timeout=15)
        
        if response.status_code != 200:
            print(f"⚠️  TBA API returned {response.status_code}")
            return match_times
        
        tba_matches = response.json()
        
        for tba_match in tba_matches:
            comp_level = tba_match.get('comp_level', 'qm')
            match_num = tba_match.get('match_number')
            set_number = tba_match.get('set_number', 0)
            match_type = comp_level_map.get(comp_level, 'Qualification')
            
            # For playoff matches, format as "set-match" if needed
            if comp_level in ['ef', 'qf', 'sf', 'f'] and set_number > 0:
                display_match_number = f"{set_number}-{match_num}"
            else:
                display_match_number = str(match_num)
            
            # Get both scheduled and actual times from TBA
            scheduled_time = tba_match.get('time')  # Unix timestamp - original scheduled
            actual_time = tba_match.get('actual_time')  # Unix timestamp - when actually played
            
            scheduled = None
            actual = None
            
            if scheduled_time:
                try:
                    scheduled = datetime.fromtimestamp(scheduled_time, tz=timezone.utc)
                except Exception as e:
                    print(f"Error parsing TBA scheduled time {scheduled_time}: {e}")
            
            if actual_time:
                try:
                    actual = datetime.fromtimestamp(actual_time, tz=timezone.utc)
                except Exception as e:
                    print(f"Error parsing TBA actual time {actual_time}: {e}")
            
            if scheduled or actual:
                match_times[(match_type, display_match_number)] = (scheduled, actual)
        
    except Exception as e:
        print(f"❌ Error fetching from TBA API: {e}")
    
    return match_times


class ScheduleAdjuster:
    """
    Tracks schedule delays/advances and adjusts future match predictions
    
    Example:
    - Match 5 was scheduled for 2:00 PM
    - It's now 2:20 PM and API shows it was played at 2:16 PM
    - Event is 16 minutes behind schedule
    - All future match times should be adjusted by +16 minutes
    """
    
    def __init__(self, event, scouting_team_number=None):
        """
        Initialize schedule adjuster for an event
        
        Args:
            event: Event model instance
            scouting_team_number: Optional team number to scope queries
        """
        self.event = event
        self.scouting_team_number = scouting_team_number
        self.schedule_offset = timedelta(0)  # How far behind/ahead (positive = behind)
        self.confidence = 0.0  # 0-1 confidence in the offset calculation
        
    def analyze_schedule_variance(self):
        """
        Analyze completed matches to determine if event is behind/ahead of schedule
        
        Returns:
            dict with:
                - offset_minutes: Average delay in minutes (positive = behind, negative = ahead)
                - confidence: 0-1 confidence score
                - sample_size: Number of matches analyzed
                - recent_offset_minutes: Offset from most recent matches (more accurate)
        """
        # Get ALL matches from this event (Practice, Qualification, Playoff, etc.)
        matches = Match.query.filter_by(event_id=self.event.id)
        
        if self.scouting_team_number:
            matches = matches.filter_by(scouting_team_number=self.scouting_team_number)
        
        matches = matches.filter(
            Match.scheduled_time.isnot(None)
        ).order_by(
            Match.match_type,  # Group by type first
            Match.match_number  # Then by number within type
        ).all()
        
        if not matches:
            print(f"⚠️  No matches with scheduled times found for event {self.event.code}")
            return {
                'offset_minutes': 0,
                'confidence': 0.0,
                'sample_size': 0,
                'recent_offset_minutes': 0
            }
        
        # Fetch actual times from both FIRST and TBA APIs
        print(f"🔍 Fetching match times for {self.event.code}...")
        
        # Get preferred API source
        preferred_api = get_preferred_api_source()
        
        match_scheduled_times = {}
        match_actual_times = {}
        api_match_types = {}
        
        # Try preferred API first
        if preferred_api == 'first':
            print(f"   Trying FIRST API first...")
            first_times = fetch_actual_times_from_first(self.event.code, self.event.timezone)
            
            # Process FIRST API results
            for match_key, (scheduled, actual) in first_times.items():
                match_type, match_num = match_key
                api_match_types[match_type] = api_match_types.get(match_type, 0) + 1
                
                if scheduled:
                    match_scheduled_times[match_key] = scheduled
                if actual:
                    match_actual_times[match_key] = actual
            
            # If FIRST didn't give us much, try TBA as backup
            if len(match_actual_times) < 5:
                print(f"   FIRST API returned limited data, trying TBA as backup...")
                tba_times = fetch_actual_times_from_tba(self.event.code, self.event.timezone)
                
                for match_key, (scheduled, actual) in tba_times.items():
                    match_type, match_num = match_key
                    if match_type not in api_match_types:
                        api_match_types[match_type] = 0
                    
                    # Only add if we don't already have this match
                    if match_key not in match_scheduled_times and scheduled:
                        match_scheduled_times[match_key] = scheduled
                        api_match_types[match_type] += 1
                    if match_key not in match_actual_times and actual:
                        match_actual_times[match_key] = actual
        else:
            # TBA preferred
            print(f"   Trying TBA first...")
            tba_times = fetch_actual_times_from_tba(self.event.code, self.event.timezone)
            
            for match_key, (scheduled, actual) in tba_times.items():
                match_type, match_num = match_key
                api_match_types[match_type] = api_match_types.get(match_type, 0) + 1
                
                if scheduled:
                    match_scheduled_times[match_key] = scheduled
                if actual:
                    match_actual_times[match_key] = actual
            
            # If TBA didn't give us much, try FIRST as backup
            if len(match_actual_times) < 5:
                print(f"   TBA returned limited data, trying FIRST API as backup...")
                first_times = fetch_actual_times_from_first(self.event.code, self.event.timezone)
                
                for match_key, (scheduled, actual) in first_times.items():
                    match_type, match_num = match_key
                    if match_type not in api_match_types:
                        api_match_types[match_type] = 0
                    
                    # Only add if we don't already have this match
                    if match_key not in match_scheduled_times and scheduled:
                        match_scheduled_times[match_key] = scheduled
                        api_match_types[match_type] += 1
                    if match_key not in match_actual_times and actual:
                        match_actual_times[match_key] = actual
        
        print(f"🔍 APIs returned: {', '.join(f'{count} {mtype}' for mtype, count in api_match_types.items())}")
        
        print(f"📋 Found {len(match_scheduled_times)} matches with scheduled times from TBA")
        print(f"✅ Found {len(match_actual_times)} matches with actual times (completed)")
        
        # Count match types in database
        match_type_counts = {}
        for match in matches:
            match_type = match.match_type
            match_type_counts[match_type] = match_type_counts.get(match_type, 0) + 1
        
        print(f"📊 Database has: {', '.join(f'{count} {mtype}' for mtype, count in match_type_counts.items())}")
        
        # Compare scheduled vs actual times for completed matches
        delays = []
        recent_delays = []  # Last 3 matches - more relevant to current schedule
        match_types_analyzed = {}
        matches_not_found = []
        
        for match in matches:
            # Convert match_number to string to handle both int (quals) and string (playoffs like "1-1")
            match_number_str = str(match.match_number)
            match_key = (match.match_type, match_number_str)
            
            # Only analyze matches that have both scheduled and actual times
            if match_key in match_scheduled_times and match_key in match_actual_times:
                scheduled_time = match_scheduled_times[match_key]
                actual_time = match_actual_times[match_key]
                
                # Calculate delay
                delay = actual_time - scheduled_time
                delay_minutes = delay.total_seconds() / 60
                
                delays.append(delay_minutes)
                
                # Track match types analyzed
                match_type = match.match_type
                match_types_analyzed[match_type] = match_types_analyzed.get(match_type, 0) + 1
                
                # Track recent matches separately (last 3)
                if len(recent_delays) < 3 or len(delays) > len(matches) - 3:
                    recent_delays.append(delay_minutes)
                
                # Log for debugging
                event_tz = self.event.timezone
                scheduled_str = format_time_with_timezone(scheduled_time, event_tz, '%I:%M %p')
                actual_str = format_time_with_timezone(actual_time, event_tz, '%I:%M %p')
                
                print(f"  {match.match_type} {match.match_number}: Scheduled {scheduled_str}, "
                      f"Actual {actual_str}, Delay: {delay_minutes:+.1f} min")
            else:
                # Track matches that weren't found in TBA data
                matches_not_found.append((match.match_type, match_number_str))
        
        # Show what matches weren't matched
        if matches_not_found:
            not_found_by_type = {}
            for match_type, match_num in matches_not_found:
                not_found_by_type[match_type] = not_found_by_type.get(match_type, 0) + 1
            print(f"\n⚠️  Matches in DB but not matched with TBA: {', '.join(f'{count} {mtype}' for mtype, count in not_found_by_type.items())}")
            # Show first few examples for debugging
            print(f"   Examples: {', '.join(f'{mt} {mn}' for mt, mn in matches_not_found[:5])}")
        
        if not delays:
            print(f"ℹ️  No completed matches with actual times yet for {self.event.code}")
            return {
                'offset_minutes': 0,
                'confidence': 0.0,
                'sample_size': 0,
                'recent_offset_minutes': 0
            }
        
        # Calculate average offset
        avg_offset = sum(delays) / len(delays)
        recent_offset = sum(recent_delays) / len(recent_delays) if recent_delays else avg_offset
        
        # Calculate confidence based on:
        # 1. Sample size (more matches = higher confidence)
        # 2. Consistency (less variance = higher confidence)
        sample_confidence = min(len(delays) / 10, 1.0)  # Max confidence at 10+ matches
        
        variance = sum((d - avg_offset) ** 2 for d in delays) / len(delays)
        std_dev = variance ** 0.5
        consistency_confidence = max(0, 1 - (std_dev / 30))  # Low confidence if std dev > 30 min
        
        confidence = (sample_confidence * 0.6) + (consistency_confidence * 0.4)
        
        print(f"\n📊 Schedule Analysis for {self.event.code}:")
        print(f"   Average offset: {avg_offset:+.1f} minutes ({'behind' if avg_offset > 0 else 'ahead of'} schedule)")
        print(f"   Recent offset: {recent_offset:+.1f} minutes (last {len(recent_delays)} matches)")
        print(f"   Confidence: {confidence:.1%}")
        print(f"   Sample size: {len(delays)} completed matches")
        print(f"   Match types: {', '.join(f'{count} {mtype}' for mtype, count in match_types_analyzed.items())}")
        print(f"   Std deviation: {std_dev:.1f} minutes")
        
        self.schedule_offset = timedelta(minutes=recent_offset)
        self.confidence = confidence
        
        return {
            'offset_minutes': recent_offset,
            'confidence': confidence,
            'sample_size': len(delays),
            'recent_offset_minutes': recent_offset
        }
    
    def adjust_future_match_times(self, min_confidence=0.3):
        """
        Apply schedule offset to future matches that haven't been played yet
        
        Args:
            min_confidence: Minimum confidence threshold to apply adjustments (default 0.3)
            
        Returns:
            Number of matches adjusted
        """
        if self.confidence < min_confidence:
            print(f"⚠️  Confidence {self.confidence:.1%} below threshold {min_confidence:.1%}, "
                  f"not adjusting schedule")
            return 0
        
        if abs(self.schedule_offset.total_seconds() / 60) < 2:
            print(f"ℹ️  Schedule offset {self.schedule_offset.total_seconds() / 60:.1f} min is minimal, "
                  f"no adjustment needed")
            return 0
        
        # Get future matches (scheduled time is in the future)
        now = datetime.now(timezone.utc)
        
        future_matches = Match.query.filter_by(event_id=self.event.id)
        
        if self.scouting_team_number:
            future_matches = future_matches.filter_by(scouting_team_number=self.scouting_team_number)
        
        future_matches = future_matches.filter(
            Match.scheduled_time > now
        ).all()
        
        if not future_matches:
            print(f"ℹ️  No future matches to adjust for {self.event.code}")
            return 0
        
        offset_minutes = self.schedule_offset.total_seconds() / 60
        print(f"\n🔧 Adjusting {len(future_matches)} future matches by {offset_minutes:+.1f} minutes...")
        
        adjusted_count = 0
        
        for match in future_matches:
            if match.scheduled_time:
                # Store original scheduled time if not already stored
                # (we'll add this field in migration)
                
                # Apply offset to create adjusted predicted time
                adjusted_time = match.scheduled_time + self.schedule_offset
                
                # Update predicted_time field with adjusted schedule
                if match.predicted_time != adjusted_time:
                    match.predicted_time = adjusted_time
                    adjusted_count += 1
                    
                    event_tz = self.event.timezone
                    orig_str = format_time_with_timezone(match.scheduled_time, event_tz, '%I:%M %p')
                    adj_str = format_time_with_timezone(adjusted_time, event_tz, '%I:%M %p')
                    
                    print(f"  Match {match.match_number}: {orig_str} → {adj_str}")
        
        if adjusted_count > 0:
            db.session.commit()
            print(f"✅ Adjusted {adjusted_count} future match predictions")
            
            # Update event's schedule offset field
            self.event.schedule_offset = int(offset_minutes)
            db.session.commit()
        
        return adjusted_count
    
    def should_reschedule_notifications(self):
        """
        Determine if notifications should be rescheduled based on schedule changes
        
        Returns:
            bool: True if reschedule is needed
        """
        # Reschedule if:
        # 1. Confidence is high enough (>30%)
        # 2. Offset is significant (>5 minutes)
        # 3. Event has an updated offset value
        
        offset_minutes = abs(self.schedule_offset.total_seconds() / 60)
        
        return (
            self.confidence >= 0.3 and 
            offset_minutes >= 5 and
            self.event.schedule_offset is not None
        )


def update_event_schedule(event_code, scouting_team_number=None, reschedule_notifications=True):
    """
    Analyze and adjust schedule for an event
    
    Args:
        event_code: Event code to analyze
        scouting_team_number: Optional team number to scope
        reschedule_notifications: Whether to reschedule pending notifications
        
    Returns:
        dict with adjustment results
    """
    # Get event
    query = Event.query.filter_by(code=event_code)
    if scouting_team_number:
        query = query.filter_by(scouting_team_number=scouting_team_number)
    
    event = query.first()
    if not event:
        return {
            'success': False,
            'error': f'Event {event_code} not found'
        }
    
    # Create adjuster and analyze
    adjuster = ScheduleAdjuster(event, scouting_team_number)
    analysis = adjuster.analyze_schedule_variance()
    
    # Adjust future matches if confidence is sufficient
    adjusted_count = adjuster.adjust_future_match_times()
    
    # Reschedule notifications if needed
    rescheduled_count = 0
    if reschedule_notifications and adjuster.should_reschedule_notifications():
        print(f"\n📅 Rescheduling notifications due to schedule changes...")
        from app.utils.notification_service import schedule_notifications_for_match
        from app.models_misc import NotificationQueue
        
        # Get future matches
        now = datetime.now(timezone.utc)
        future_matches = Match.query.filter_by(event_id=event.id).filter(
            Match.scheduled_time > now
        ).all()
        
        # Clear old pending notifications for these matches
        match_ids = [m.id for m in future_matches]
        if match_ids:
            pending = NotificationQueue.query.filter(
                NotificationQueue.match_id.in_(match_ids),
                NotificationQueue.status == 'pending'
            ).all()
            
            for queue_entry in pending:
                db.session.delete(queue_entry)
            
            db.session.commit()
            print(f"  Cleared {len(pending)} old pending notifications")
        
        # Reschedule with adjusted times
        for match in future_matches:
            count = schedule_notifications_for_match(match)
            rescheduled_count += count
        
        print(f"✅ Rescheduled {rescheduled_count} notifications")
    
    return {
        'success': True,
        'event_code': event_code,
        'analysis': analysis,
        'adjusted_matches': adjusted_count,
        'rescheduled_notifications': rescheduled_count,
        'should_notify_users': adjuster.should_reschedule_notifications()
    }


def update_all_active_events_schedule():
    """
    Update schedule adjustments for all active events
    
    Returns:
        List of results for each event
    """
    from app.utils.config_manager import load_game_config
    from app.models import User
    
    results = []
    
    # Get all unique scouting teams
    team_numbers = set()
    try:
        for rec in User.query.with_entities(User.scouting_team_number).filter(
            User.scouting_team_number.isnot(None)
        ).distinct().all():
            if rec[0] is not None:
                team_numbers.add(rec[0])
    except Exception:
        pass
    
    # For each scouting team, check their configured event
    for team_number in sorted(team_numbers):
        try:
            game_config = load_game_config(team_number=team_number)
            event_code = game_config.get('current_event_code')
            
            if event_code:
                print(f"\n{'='*60}")
                print(f"🏢 Processing team {team_number}, event {event_code}")
                print(f"{'='*60}")
                
                result = update_event_schedule(event_code, team_number)
                results.append(result)
        except Exception as e:
            print(f"❌ Error updating schedule for team {team_number}: {e}")
            import traceback
            traceback.print_exc()
    
    return results
