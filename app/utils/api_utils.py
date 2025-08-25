import requests
import json
import os
import base64
from flask import current_app
from .tba_api_utils import (
    TBAApiError, get_tba_teams_at_event, get_tba_event_matches, 
    get_tba_event_details, tba_team_to_db_format, tba_match_to_db_format,
    tba_event_to_db_format, construct_tba_event_key, construct_tba_team_key
)
from app.utils.config_manager import get_current_game_config

class ApiError(Exception):
    """Exception for API errors"""
    pass

def get_preferred_api_source():
    """Get preferred API source from config"""
    game_config = get_current_game_config()
    return game_config.get('preferred_api_source', 'first')  # Default to FIRST API

def get_api_key():
    """Get API key from config - prefer team-specific instance config."""
    # Prefer team-specific instance config when available
    try:
        from flask_login import current_user
        team_number = None
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
            team_number = current_user.scouting_team_number

        if team_number:
            from app.utils.config_manager import load_game_config
            game_config = load_game_config(team_number=team_number)
            api_settings = game_config.get('api_settings', {})
            api_key = api_settings.get('auth_token')
            if api_key and isinstance(api_key, str):
                return api_key.strip()
    except Exception:
        pass

    # Next, check environment variable
    api_key = os.environ.get('FRC_API_KEY')
    if api_key and isinstance(api_key, str):
        return api_key.strip()

    # Finally, check global app config
    api_key = current_app.config.get('API_KEY')
    if isinstance(api_key, str):
        api_key = api_key.strip()

    return api_key

def get_api_headers():
    """Get auth headers for FIRST API"""
    auth_token = get_api_key()
    
    # If we don't have an API key, use minimal headers 
    # (some endpoints may still work without auth)
    if not auth_token:
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    # For FIRST API, auth format is Basic Username:Auth_Token
    # Get username from config
    api_settings = get_current_game_config().get('api_settings', {})
    username = api_settings.get('username', '')
    
    if username and auth_token:
        # Create the auth string as "username:auth_token"
        auth_string = f"{username}:{auth_token}"
        # Encode to base64
        auth_bytes = auth_string.encode('ascii')
        base64_bytes = base64.b64encode(auth_bytes)
        base64_auth = base64_bytes.decode('ascii')
        
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {base64_auth}'
        }
    
    # Fallback to just using the token directly
    # Some setups only provide a token. Construct a Basic auth blob with an empty
    # username so the header is syntactically correct (Base64 of ":token").
    # This avoids sending the raw token as-is which was likely rejected by some
    # servers and resulted in 401 responses.
    try:
        fallback_string = f":{auth_token}"
        fallback_b64 = base64.b64encode(fallback_string.encode('ascii')).decode('ascii')
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Basic {fallback_b64}'
        }
    except Exception:
        # Last-resort minimal headers
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

def get_teams(event_code):
    """Get teams from FIRST API for a specific event"""
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    
    # FIRST API has multiple endpoint formats for teams at an event
    # Try them in sequence until one works
    endpoints_to_try = [
        f"/v2.0/{season}/teams/event/{event_code}",               # Standard endpoint
        f"/v2.0/{season}/teams?eventCode={event_code}",           # Alternative format
        f"/v2.0/{season}/schedule/{event_code}/teams",            # Schedule-based team list
        f"/v2.0/{season}/teams/keys?eventCode={event_code}"       # Team keys endpoint
    ]
    
    last_error = None
    
    for endpoint in endpoints_to_try:
        api_url = f"{base_url}{endpoint}"
        try:
            print(f"Trying teams endpoint: {api_url}")
            headers = get_api_headers()
            # Print which header keys are being sent (do not print values)
            print(f"Using headers: {list(headers.keys())}")

            response = requests.get(
                api_url,
                headers=headers,
                timeout=15  # Increased timeout for potentially slow API responses
            )
            
            # Log response info for debugging
            print(f"Teams response status: {response.status_code}")
            
            if response.status_code == 200:
                print("Success! API returned team data.")
                data = response.json()
                
                # Check different response formats
                if 'teams' in data:
                    return data.get('teams', [])
                elif 'Teams' in data:
                    return data.get('Teams', [])
                elif 'teamCountTotal' in data:
                    # Some endpoints include a wrapper object
                    for key in data.keys():
                        if isinstance(data[key], list) and len(data[key]) > 0:
                            return data[key]
                else:
                    print(f"Warning: Successful response but unknown data format. Keys: {list(data.keys())}")
                    # If we got data but in an unknown format, try to find a list that might contain teams
                    for key, value in data.items():
                        if isinstance(value, list) and len(value) > 0:
                            return value
                    
                    # Last resort: if there's only one key with a list value, return that
                    list_values = [v for v in data.values() if isinstance(v, list)]
                    if len(list_values) == 1:
                        return list_values[0]
                        
                    return []
            else:
                # Store error for later if this endpoint doesn't work
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', f"HTTP {response.status_code}")
                except:
                    error_msg = f"HTTP {response.status_code}"
                last_error = f"API Error: {error_msg}"
                print(f"Endpoint {api_url} failed: {last_error}")
                if response.status_code == 401:
                    # Helpful debug without printing secrets
                    print("Authentication failed (401) when contacting FIRST API.")
                    print(f"Authorization header present: {'Authorization' in headers}")
                    try:
                        print(f"Response body: {response.text}")
                    except Exception:
                        pass
                # Continue to try the next endpoint
        
        except Exception as e:
            last_error = f"Request error: {str(e)}"
            print(f"Endpoint {api_url} exception: {last_error}")
            # Continue to try the next endpoint
    
    # If we get here, all endpoints failed
    print(f"All teams API endpoints failed. Last error: {last_error}")
    
    # Check if the event code looks valid
    if not event_code or len(event_code) < 3:
        raise ApiError(f"Invalid event code '{event_code}'. Event codes are typically 4-5 characters (e.g., CALA, NYRO)")
        
    # If we got here, raise the last error we encountered
    raise ApiError(f"Error getting teams: {last_error}")

def get_matches(event_code):
    """Get matches from FIRST API for a specific event"""
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    
    # FIRST API has multiple endpoint formats for match schedules
    # Try them in sequence until one works
    endpoints_to_try = [
        f"/v2.0/{season}/schedule/{event_code}",                 # Basic endpoint for all matches
        f"/v2.0/{season}/matches/{event_code}",                  # Alternative endpoint for all matches
        f"/v2.0/{season}/schedule/{event_code}?tournamentLevel=all",  # Explicitly request all tournament levels
        f"/v2.0/{season}/scores/{event_code}/all",              # Scores endpoint for all match types
        # Fall back to qualification-specific endpoints if others fail
        f"/v2.0/{season}/schedule/{event_code}?tournamentLevel=qual",
        f"/v2.0/{season}/scores/{event_code}/qual",
    ]
    
    last_error = None
    
    for endpoint in endpoints_to_try:
        api_url = f"{base_url}{endpoint}"
        try:
            print(f"Trying endpoint: {api_url}")
            headers = get_api_headers()
            print(f"Using headers: {list(headers.keys())}")

            response = requests.get(
                api_url,
                headers=headers,
                timeout=15  # Increased timeout for potentially slow API responses
            )
            
            # Log response info for debugging
            print(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                print("Success! API returned data.")
                data = response.json()
                
                # Check different response formats
                if 'Schedule' in data:
                    return data.get('Schedule', [])
                elif 'schedule' in data:
                    return data.get('schedule', [])
                elif 'Matches' in data:
                    return data.get('Matches', [])
                elif 'matches' in data:
                    return data.get('matches', [])
                else:
                    print(f"Warning: Successful response but unknown data format. Keys: {data.keys()}")
                    # If this endpoint worked but data format is unknown, just return the data
                    # and let the converter function handle it
                    return list(data.values())[0] if data else []
            else:
                # Store error for later if this endpoint doesn't work
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', f"HTTP {response.status_code}")
                except:
                    error_msg = f"HTTP {response.status_code}"
                last_error = f"API Error: {error_msg}"
                print(f"Endpoint {api_url} failed: {last_error}")
                if response.status_code == 401:
                    print("Authentication failed (401) when contacting FIRST API for matches.")
                    print(f"Authorization header present: {'Authorization' in headers}")
                    try:
                        print(f"Response body: {response.text}")
                    except Exception:
                        pass
                # Continue to try the next endpoint
        
        except Exception as e:
            last_error = f"Request error: {str(e)}"
            print(f"Endpoint {api_url} exception: {last_error}")
            # Continue to try the next endpoint
    
    # If we get here, all endpoints failed
    print(f"All API endpoints failed. Last error: {last_error}")
    
    # Check if the event code looks valid
    if not event_code or len(event_code) < 3:
        raise ApiError(f"Invalid event code '{event_code}'. Event codes are typically 4-5 characters (e.g., CALA, NYRO)")
        
    # Check if the season is reasonable (between 2000-2050)
    if season < 2000 or season > 2050:
        raise ApiError(f"Season value ({season}) appears invalid. Check your configuration.")
    
    # If we got here, raise the last error we encountered
    raise ApiError(f"Error getting matches: {last_error}")

def api_to_db_team_conversion(api_team):
    """Convert API team format to database format"""
    # Handle different API response formats
    if 'teamNumber' in api_team:
        # New API format
        return {
            'team_number': api_team.get('teamNumber'),
            'team_name': api_team.get('nameShort', ''),
            'location': f"{api_team.get('city', '')}, {api_team.get('stateProv', '')}"
        }
    elif 'teamKey' in api_team:
        # New API format with teamKey
        try:
            team_number = int(api_team.get('teamKey', '').replace('frc', ''))
        except:
            team_number = None
            
        return {
            'team_number': team_number,
            'team_name': api_team.get('nameShort', ''),
            'location': f"{api_team.get('city', '')}, {api_team.get('stateProv', '')}"
        }
    else:
        # Handle unknown formats
        return {}

def get_match_type(api_match):
    """Extract and normalize match type from various API response formats"""
    match_type_map = {
        'qm': 'Qualification',
        'qual': 'Qualification',
        'qualification': 'Qualification',
        'qf': 'Playoff',
        'sf': 'Playoff',
        'f': 'Playoff',
        'playoff': 'Playoff',
        'quarterfinal': 'Playoff',
        'semifinal': 'Playoff',
        'final': 'Playoff',
        'pr': 'Practice',
        'practice': 'Practice'
    }
    
    # Try different fields that might contain match type info
    for field in ['tournamentLevel', 'comp_level', 'tournament_level', 'type', 'matchType']:
        if field in api_match:
            api_match_type = str(api_match.get(field, '')).lower()
            match_type = match_type_map.get(api_match_type, None)
            if match_type:
                return match_type
    
    # Check for descriptive fields that might indicate match type
    if 'description' in api_match:
        desc = api_match['description'].lower()
        if 'practice' in desc:
            return 'Practice'
        elif 'qualification' in desc or 'qual' in desc:
            return 'Qualification'
        elif any(playoff_type in desc for playoff_type in ['playoff', 'quarter', 'semi', 'final']):
            return 'Playoff'
            
    # Default to qualification if we can't determine type
    return 'Qualification'

def api_to_db_match_conversion(api_match, event_id):
    """Convert API match format to database format"""
    # Extract match details
    match_number = api_match.get('matchNumber')
    
    # Get the standardized match type from our helper function
    match_type = get_match_type(api_match)
    
    # Extract teams
    red_alliance = []
    blue_alliance = []
    
    # Handle different API response formats
    if 'teams' in api_match:
        # New API format with teams array
        for team in api_match.get('teams', []):
            if team.get('station', '').startswith('Red'):
                # Extract just the team number from the team key (e.g., "frc254" -> "254")
                team_number = team.get('teamNumber')
                if team_number:
                    red_alliance.append(str(team_number))
            elif team.get('station', '').startswith('Blue'):
                team_number = team.get('teamNumber')
                if team_number:
                    blue_alliance.append(str(team_number))
    elif 'alliances' in api_match:
        # TBA API format with alliances object
        if 'red' in api_match.get('alliances', {}):
            for team in api_match.get('alliances', {}).get('red', {}).get('team_keys', []):
                red_alliance.append(team.replace('frc', ''))
        if 'blue' in api_match.get('alliances', {}):
            for team in api_match.get('alliances', {}).get('blue', {}).get('team_keys', []):
                blue_alliance.append(team.replace('frc', ''))
    
    # Extract scores if available
    red_score = None
    blue_score = None
    winner = None
    
    if 'scoreRedFinal' in api_match and 'scoreBlueFinal' in api_match:
        red_score = api_match.get('scoreRedFinal')
        blue_score = api_match.get('scoreBlueFinal')
        
        # Determine winner
        if red_score > blue_score:
            winner = 'red'
        elif blue_score > red_score:
            winner = 'blue'
        else:
            winner = 'tie'
    
    # Build match data dictionary
    match_data = {
        'match_number': match_number,
        'match_type': match_type,
        'event_id': event_id,
        'red_alliance': ','.join(red_alliance),
        'blue_alliance': ','.join(blue_alliance),
        'red_score': red_score,
        'blue_score': blue_score,
        'winner': winner
    }
    
    return match_data

def get_event_details(event_code):
    """Get event details from FIRST API"""
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    
    api_url = f"{base_url}/v2.0/{season}/events?eventCode={event_code}"
    
    try:
        response = requests.get(
            api_url,
            headers=get_api_headers(),
            timeout=10
        )
        
        # Check for errors
        if response.status_code != 200:
            error_message = f"API Error: {response.status_code}"
            try:
                error_data = response.json()
                if 'message' in error_data:
                    error_message = f"API Error: {error_data['message']}"
            except:
                pass
            
            raise ApiError(error_message)
        
        # Get the first event from the response
        events = response.json().get('Events', [])
        if events:
            return events[0]
        else:
            raise ApiError(f"Event {event_code} not found")
        
    except requests.RequestException as e:
        raise ApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise ApiError(f"Error getting event details: {str(e)}")

# Dual API Support Functions
def get_teams_dual_api(event_code):
    """Get teams from either FIRST API or TBA API based on configuration"""
    preferred_source = get_preferred_api_source()
    
    try:
        if preferred_source == 'tba':
            print(f"Using TBA API for teams at event {event_code}")
            # Convert event code to TBA format
            game_config = get_current_game_config()
            season = game_config.get('season', 2026)
            tba_event_key = construct_tba_event_key(event_code, season)
            
            # Get teams from TBA
            tba_teams = get_tba_teams_at_event(tba_event_key)
            
            # Convert to database format
            teams_db_format = []
            for tba_team in tba_teams:
                team_data = tba_team_to_db_format(tba_team)
                if team_data and team_data.get('team_number'):
                    teams_db_format.append(team_data)
            
            return teams_db_format
        else:
            print(f"Using FIRST API for teams at event {event_code}")
            # Use existing FIRST API function
            api_teams = get_teams(event_code)
            
            # Convert to database format
            teams_db_format = []
            for api_team in api_teams:
                team_data = api_to_db_team_conversion(api_team)
                if team_data and team_data.get('team_number'):
                    teams_db_format.append(team_data)
            
            return teams_db_format
    
    except (ApiError, TBAApiError) as e:
        print(f"Primary API ({preferred_source}) failed: {str(e)}")
        
        # Try fallback API
        fallback_source = 'first' if preferred_source == 'tba' else 'tba'
        print(f"Trying fallback API: {fallback_source}")
        
        try:
            if fallback_source == 'tba':
                game_config = get_current_game_config()
                season = game_config.get('season', 2026)
                tba_event_key = construct_tba_event_key(event_code, season)
                
                tba_teams = get_tba_teams_at_event(tba_event_key)
                
                teams_db_format = []
                for tba_team in tba_teams:
                    team_data = tba_team_to_db_format(tba_team)
                    if team_data and team_data.get('team_number'):
                        teams_db_format.append(team_data)
                
                return teams_db_format
            else:
                api_teams = get_teams(event_code)
                
                teams_db_format = []
                for api_team in api_teams:
                    team_data = api_to_db_team_conversion(api_team)
                    if team_data and team_data.get('team_number'):
                        teams_db_format.append(team_data)
                
                return teams_db_format
        
        except (ApiError, TBAApiError) as fallback_error:
            print(f"Fallback API ({fallback_source}) also failed: {str(fallback_error)}")
            raise ApiError(f"Both APIs failed. Primary ({preferred_source}): {str(e)}, Fallback ({fallback_source}): {str(fallback_error)}")

def get_matches_dual_api(event_code):
    """Get matches from either FIRST API or TBA API based on configuration"""
    preferred_source = get_preferred_api_source()
    
    try:
        if preferred_source == 'tba':
            print(f"Using TBA API for matches at event {event_code}")
            # Convert event code to TBA format
            game_config = get_current_game_config()
            season = game_config.get('season', 2026)
            tba_event_key = construct_tba_event_key(event_code, season)
            
            # Get matches from TBA
            tba_matches = get_tba_event_matches(tba_event_key)
            
            # Convert to database format (we'll need event_id later)
            matches_db_format = []
            for tba_match in tba_matches:
                match_data = tba_match_to_db_format(tba_match, None)  # event_id will be set later
                if match_data:
                    matches_db_format.append(match_data)
            
            return matches_db_format
        else:
            print(f"Using FIRST API for matches at event {event_code}")
            # Use existing FIRST API function
            api_matches = get_matches(event_code)
            
            # Convert to database format
            matches_db_format = []
            for api_match in api_matches:
                match_data = api_to_db_match_conversion(api_match, None)  # event_id will be set later
                if match_data:
                    matches_db_format.append(match_data)
            
            return matches_db_format
    
    except (ApiError, TBAApiError) as e:
        print(f"Primary API ({preferred_source}) failed: {str(e)}")
        
        # Try fallback API
        fallback_source = 'first' if preferred_source == 'tba' else 'tba'
        print(f"Trying fallback API: {fallback_source}")
        
        try:
            if fallback_source == 'tba':
                game_config = get_current_game_config()
                season = game_config.get('season', 2026)
                tba_event_key = construct_tba_event_key(event_code, season)
                
                tba_matches = get_tba_event_matches(tba_event_key)
                
                matches_db_format = []
                for tba_match in tba_matches:
                    match_data = tba_match_to_db_format(tba_match, None)
                    if match_data:
                        matches_db_format.append(match_data)
                
                return matches_db_format
            else:
                api_matches = get_matches(event_code)
                
                matches_db_format = []
                for api_match in api_matches:
                    match_data = api_to_db_match_conversion(api_match, None)
                    if match_data:
                        matches_db_format.append(match_data)
                
                return matches_db_format
        
        except (ApiError, TBAApiError) as fallback_error:
            print(f"Fallback API ({fallback_source}) also failed: {str(fallback_error)}")
            raise ApiError(f"Both APIs failed. Primary ({preferred_source}): {str(e)}, Fallback ({fallback_source}): {str(fallback_error)}")

def get_event_details_dual_api(event_code):
    """Get event details from either FIRST API or TBA API based on configuration"""
    preferred_source = get_preferred_api_source()
    
    try:
        if preferred_source == 'tba':
            print(f"Using TBA API for event details: {event_code}")
            # Convert event code to TBA format
            game_config = get_current_game_config()
            season = game_config.get('season', 2026)
            tba_event_key = construct_tba_event_key(event_code, season)
            
            # Get event details from TBA
            tba_event = get_tba_event_details(tba_event_key)
            
            if tba_event:
                # Convert to database format
                return tba_event_to_db_format(tba_event)
            else:
                return None
        else:
            print(f"Using FIRST API for event details: {event_code}")
            # Use existing FIRST API function
            return get_event_details(event_code)
    
    except (ApiError, TBAApiError) as e:
        print(f"Primary API ({preferred_source}) failed: {str(e)}")
        
        # Try fallback API
        fallback_source = 'first' if preferred_source == 'tba' else 'tba'
        print(f"Trying fallback API: {fallback_source}")
        
        try:
            if fallback_source == 'tba':
                game_config = get_current_game_config()
                season = game_config.get('season', 2026)
                tba_event_key = construct_tba_event_key(event_code, season)
                
                tba_event = get_tba_event_details(tba_event_key)
                
                if tba_event:
                    return tba_event_to_db_format(tba_event)
                else:
                    return None
            else:
                return get_event_details(event_code)
        
        except (ApiError, TBAApiError) as fallback_error:
            print(f"Fallback API ({fallback_source}) also failed: {str(fallback_error)}")
            raise ApiError(f"Both APIs failed. Primary ({preferred_source}): {str(e)}, Fallback ({fallback_source}): {str(fallback_error)}")