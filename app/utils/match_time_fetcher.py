"""
Match Time Fetcher
Updates match scheduled times from FIRST and TBA APIs
"""
import requests
from datetime import datetime
from flask import current_app
from app import db
from app.models import Match, Event
from app.utils.api_utils import get_api_headers, get_preferred_api_source
from app.utils.config_manager import get_current_game_config


def fetch_match_times_from_first(event_code):
    """
    Fetch match scheduled times from FIRST API
    
    Returns:
        dict mapping (match_type, match_number) -> datetime
    """
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    headers = get_api_headers()
    
    match_times = {}
    
    # Schedule endpoints for different match types
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
                    match_num = match_data.get('matchNumber')
                    scheduled_time_str = match_data.get('startTime')
                    
                    if match_num and scheduled_time_str:
                        try:
                            # Parse ISO 8601 format: "2024-03-15T09:30:00"
                            scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
                            match_times[(match_type, match_num)] = scheduled_time
                        except Exception as e:
                            print(f"Error parsing time '{scheduled_time_str}': {e}")
                
                print(f"✅ Fetched {len(matches)} {match_type} match times from FIRST API")
            else:
                print(f"⚠️  FIRST API returned {response.status_code} for {endpoint}")
                
        except Exception as e:
            print(f"❌ Error fetching match times from FIRST API: {e}")
    
    return match_times


def fetch_match_times_from_tba(event_code):
    """
    Fetch match scheduled/predicted times from The Blue Alliance API
    
    Returns:
        dict mapping (match_type, match_number) -> (scheduled_time, predicted_time)
    """
    from app.utils.tba_api_utils import get_tba_api_headers, construct_tba_event_key
    
    base_url = 'https://www.thebluealliance.com/api/v3'
    year = get_current_game_config().get('season', 2026)
    
    # Construct TBA event key
    event_key = construct_tba_event_key(event_code, year)
    
    match_times = {}
    
    try:
        api_url = f"{base_url}/event/{event_key}/matches"
        response = requests.get(api_url, headers=get_tba_api_headers(), timeout=15)
        
        if response.status_code == 200:
            matches = response.json()
            
            # Map TBA comp_level to our match_type
            comp_level_map = {
                'qm': 'Qualification',
                'ef': 'Elimination',
                'qf': 'Quarterfinals',
                'sf': 'Semifinals',
                'f': 'Finals',
                'pr': 'Practice'
            }
            
            for match_data in matches:
                comp_level = match_data.get('comp_level', 'qm')
                match_num = match_data.get('match_number')
                match_type = comp_level_map.get(comp_level, 'Qualification')
                
                # TBA provides both actual_time and predicted_time
                actual_time = match_data.get('actual_time')  # Unix timestamp
                predicted_time = match_data.get('predicted_time')  # Unix timestamp
                
                scheduled = None
                predicted = None
                
                if actual_time:
                    try:
                        scheduled = datetime.fromtimestamp(actual_time)
                    except Exception as e:
                        print(f"Error parsing actual_time {actual_time}: {e}")
                
                if predicted_time:
                    try:
                        predicted = datetime.fromtimestamp(predicted_time)
                    except Exception as e:
                        print(f"Error parsing predicted_time {predicted_time}: {e}")
                
                if scheduled or predicted:
                    match_times[(match_type, match_num)] = (scheduled, predicted)
            
            print(f"✅ Fetched {len(matches)} match times from TBA")
        else:
            print(f"⚠️  TBA API returned {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error fetching match times from TBA: {e}")
    
    return match_times


def update_match_times(event_code, scouting_team_number=None):
    """
    Update scheduled times for all matches at an event
    
    Args:
        event_code: Event code to update
        scouting_team_number: Optional team number to scope update
        
    Returns:
        Number of matches updated
    """
    print(f"\n📅 Updating match times for event {event_code}...")
    
    # Get preferred API source
    preferred_api = get_preferred_api_source()
    
    # Fetch times from APIs
    first_times = {}
    tba_times = {}
    
    if preferred_api == 'first':
        first_times = fetch_match_times_from_first(event_code)
        if not first_times:
            # Fallback to TBA
            print("⚠️  No times from FIRST API, trying TBA...")
            tba_times = fetch_match_times_from_tba(event_code)
    else:
        tba_times = fetch_match_times_from_tba(event_code)
        if not tba_times:
            # Fallback to FIRST
            print("⚠️  No times from TBA, trying FIRST API...")
            first_times = fetch_match_times_from_first(event_code)
    
    # Get event from database
    query = Event.query.filter_by(code=event_code)
    if scouting_team_number:
        query = query.filter_by(scouting_team_number=scouting_team_number)
    
    event = query.first()
    if not event:
        print(f"❌ Event {event_code} not found in database")
        return 0
    
    # Get all matches for this event
    matches = Match.query.filter_by(event_id=event.id).all()
    
    updated_count = 0
    
    for match in matches:
        match_key = (match.match_type, match.match_number)
        
        updated = False
        
        # Update from FIRST API times
        if match_key in first_times:
            scheduled_time = first_times[match_key]
            if match.scheduled_time != scheduled_time:
                match.scheduled_time = scheduled_time
                updated = True
        
        # Update from TBA times
        if match_key in tba_times:
            scheduled, predicted = tba_times[match_key]
            
            if scheduled and match.scheduled_time != scheduled:
                match.scheduled_time = scheduled
                updated = True
            
            if predicted and match.predicted_time != predicted:
                match.predicted_time = predicted
                updated = True
        
        if updated:
            updated_count += 1
    
    if updated_count > 0:
        db.session.commit()
        print(f"✅ Updated times for {updated_count} matches")
    else:
        print(f"ℹ️  No match time updates needed")
    
    return updated_count


def update_all_active_event_times():
    """
    Update match times for all active events across all scouting teams
    
    Returns:
        Total number of matches updated
    """
    from app.utils.config_manager import load_game_config
    from app.models import User
    
    total_updated = 0
    
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
                print(f"\n🏢 Processing team {team_number}, event {event_code}")
                updated = update_match_times(event_code, team_number)
                total_updated += updated
        except Exception as e:
            print(f"❌ Error updating times for team {team_number}: {e}")
    
    return total_updated
