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


def _mask(val):
    if not val:
        return None
    s = str(val)
    if len(s) <= 6:
        return '*' * len(s)
    return s[:3] + '...' + s[-3:]


def inspect_api_key_locations():
    """Return a short diagnostic string showing where API keys were found (masked).

    This helps users see which config or env var provided the key that's being
    used and where to look to fix invalid tokens.
    """
    base = os.getcwd()
    info = {'tba': [], 'first': []}

    # env and app config
    tba_env = os.environ.get('TBA_API_KEY')
    if tba_env:
        info['tba'].append(('env:TBA_API_KEY', _mask(tba_env)))
    first_env = os.environ.get('FRC_API_KEY')
    if first_env:
        info['first'].append(('env:FRC_API_KEY', _mask(first_env)))

    tba_app = current_app.config.get('TBA_API_KEY')
    if tba_app:
        info['tba'].append(('app:TBA_API_KEY', _mask(tba_app)))
    first_app = current_app.config.get('API_KEY')
    if first_app:
        info['first'].append(('app:API_KEY', _mask(first_app)))

    # game config (global)
    try:
        game_config = current_app.config.get('GAME_CONFIG', {})
        tba_settings = game_config.get('tba_api_settings', {})
        if isinstance(tba_settings, dict) and tba_settings.get('auth_key'):
            info['tba'].append(('game_config:tba_api_settings.auth_key', _mask(tba_settings.get('auth_key'))))
        api_settings = game_config.get('api_settings', {})
        if isinstance(api_settings, dict) and api_settings.get('auth_token'):
            info['first'].append(('game_config:api_settings.auth_token', _mask(api_settings.get('auth_token'))))
    except Exception:
        pass

    # scan instance/team configs for first/second matching keys (show up to 3)
    try:
        configs_dir = os.path.join(base, 'instance', 'configs')
        if os.path.isdir(configs_dir):
            for team_folder in os.listdir(configs_dir):
                cfg_path = os.path.join(configs_dir, team_folder, 'game_config.json')
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        t = data.get('tba_api_settings', {})
                        a = data.get('api_settings', {})
                        if isinstance(t, dict) and t.get('auth_key'):
                            info['tba'].append((f'instance:{team_folder}:tba_api_settings.auth_key', _mask(t.get('auth_key'))))
                        if isinstance(a, dict) and a.get('auth_token'):
                            info['first'].append((f'instance:{team_folder}:api_settings.auth_token', _mask(a.get('auth_token'))))
                    except Exception:
                        continue
    except Exception:
        pass

    parts = []
    for key in ('tba', 'first'):
        entries = info.get(key, [])
        if entries:
            parts.append(f"{key.upper()} keys found:")
            for src, masked in entries[:5]:
                parts.append(f"  - {src}: {masked}")
        else:
            parts.append(f"{key.upper()} keys found: none")

    return '\n'.join(parts)

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

    # As a final fallback, check the loaded game config (GAME_CONFIG).
    # This is where team-specific instance configs store api_settings.auth_token
    try:
        game_config = current_app.config.get('GAME_CONFIG', {})
        api_settings = game_config.get('api_settings', {})
        cfg_token = api_settings.get('auth_token')
        if cfg_token and isinstance(cfg_token, str):
            return cfg_token.strip()
    except Exception:
        pass

    # Basic placeholder detection: many default configs use phrases like
    # "your FIRST api auth token here". Avoid sending obviously placeholder
    # tokens to remote services which will generate confusing 401s.
    try:
        if isinstance(api_key, str):
            token = api_key.strip()
            low = token.lower()
            if any(x in low for x in ('your ', 'your_', 'example', 'replace', 'todo')) or len(token) < 10:
                print("FIRST API key looks like a placeholder; ignoring and returning None")
                api_key = None
            else:
                return token
    except Exception:
        pass

    # If we still don't have a key, scan instance/configs/* for a valid-looking
    # api_settings.auth_token and return the first one found.
    if not api_key:
        try:
            base = os.getcwd()
            configs_dir = os.path.join(base, 'instance', 'configs')
            if os.path.isdir(configs_dir):
                for team_folder in os.listdir(configs_dir):
                    cfg_path = os.path.join(configs_dir, team_folder, 'game_config.json')
                    if os.path.exists(cfg_path):
                        try:
                            with open(cfg_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                            api_settings = data.get('api_settings', {})
                            k = api_settings.get('auth_token')
                            if k and isinstance(k, str):
                                lk = k.strip().lower()
                                if not any(x in lk for x in ('your ', 'your_', 'example', 'replace', 'todo')) and len(k.strip()) >= 10:
                                    print(f"Found FIRST API token in team config {team_folder}; using it as fallback")
                                    return k.strip()
                        except Exception:
                            continue
        except Exception:
            pass

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

def fetch_from_endpoint(api_url, headers, timeout=15):
    """Helper function to fetch data from a single endpoint"""
    try:
        print(f"Trying endpoint: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=timeout)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
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
                print(f"Warning: Unknown data format. Keys: {data.keys()}")
                return list(data.values())[0] if data else []
        else:
            try:
                error_data = response.json()
                error_msg = error_data.get('message', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            print(f"Endpoint failed: {error_msg}")
            if response.status_code == 401:
                print("Authentication failed (401)")
                print(f"Authorization header present: {'Authorization' in headers}")
            return None
    except Exception as e:
        print(f"Endpoint exception: {str(e)}")
        return None

def merge_match_lists(matches_list1, matches_list2):
    """Merge two match lists, removing duplicates based on match number and tournament level"""
    if not matches_list1:
        return matches_list2 or []
    if not matches_list2:
        return matches_list1 or []
    
    # Create a dictionary to track unique matches
    # Key format: "tournamentLevel_matchNumber" or "matchType_matchNumber"
    unique_matches = {}

    def _has_scores(m):
        """Return True if the match object contains final/recorded scores."""
        if not m or not isinstance(m, dict):
            return False
        # FIRST API fields
        if m.get('scoreRedFinal') is not None or m.get('scoreBlueFinal') is not None:
            return True
        # Converted/internal fields
        if m.get('red_score') is not None or m.get('blue_score') is not None:
            return True
        # TBA style
        alliances = m.get('alliances')
        if isinstance(alliances, dict):
            red = alliances.get('red', {}).get('score')
            blue = alliances.get('blue', {}).get('score')
            if red is not None or blue is not None:
                return True
        return False

    # Add all matches from first list
    for match in matches_list1:
        match_number = match.get('matchNumber') or match.get('match_number')
        tournament_level = match.get('tournamentLevel') or match.get('match_type', 'Unknown')

        if match_number is not None:
            key = f"{tournament_level}_{match_number}"
            unique_matches[key] = match

    # Add matches from second list, avoiding duplicates and preferring scored records
    for match in matches_list2:
        match_number = match.get('matchNumber') or match.get('match_number')
        tournament_level = match.get('tournamentLevel') or match.get('match_type', 'Unknown')

        if match_number is not None:
            key = f"{tournament_level}_{match_number}"
            if key not in unique_matches:
                unique_matches[key] = match
            else:
                existing = unique_matches[key]
                new_has_scores = _has_scores(match)
                existing_has_scores = _has_scores(existing)

                # Prefer records that have final scores
                if new_has_scores and not existing_has_scores:
                    unique_matches[key] = match
                elif existing_has_scores and not new_has_scores:
                    # keep existing (it has scores)
                    pass
                else:
                    # If neither or both have scores, use other heuristics
                    if match.get('teams') and not existing.get('teams'):
                        unique_matches[key] = match
                    elif match.get('startTime') and not existing.get('startTime'):
                        unique_matches[key] = match
                    # otherwise keep existing
    
    return list(unique_matches.values())

def get_matches(event_code):
    """Get matches from FIRST API for a specific event with redundancy
    
    Fetches from multiple endpoints and merges results:
    - /schedule/{event_code}/qual, playoff, practice for scheduled matches
    - /matches/{event_code} for match results
    
    This ensures we get both scheduled (upcoming) and completed matches.
    """
    base_url = current_app.config.get('API_BASE_URL', 'https://frc-api.firstinspires.org')
    season = get_current_game_config().get('season', 2026)
    headers = get_api_headers()
    
    print(f"Fetching matches with redundancy for event {event_code}")
    print(f"Using headers: {list(headers.keys())}")

    all_matches = []

    # Priority 1: Fetch /matches endpoint first because it contains final scores
    matches_endpoint = f"/v2.0/{season}/matches/{event_code}"
    print(f"=== Fetching from /matches endpoint first (completed matches with results) ===")
    api_url = f"{base_url}{matches_endpoint}"
    matches_results = fetch_from_endpoint(api_url, headers)
    if matches_results:
        print(f"  Found {len(matches_results)} matches from /matches")
        all_matches = merge_match_lists(all_matches, matches_results)
    else:
        print(f"  No data from /matches endpoint")

    # Priority 2: Fetch schedule endpoints (includes future/upcoming matches)
    schedule_endpoints = [
        f"/v2.0/{season}/schedule/{event_code}/qual",      # Qualification matches
        f"/v2.0/{season}/schedule/{event_code}/playoff",   # Playoff matches
        f"/v2.0/{season}/schedule/{event_code}/practice",  # Practice matches
    ]

    print("=== Fetching from /schedule endpoints (includes upcoming matches) ===")
    for endpoint in schedule_endpoints:
        api_url = f"{base_url}{endpoint}"
        matches = fetch_from_endpoint(api_url, headers)
        if matches:
            print(f"  Found {len(matches)} matches from {endpoint}")
            all_matches = merge_match_lists(all_matches, matches)
        else:
            print(f"  No data from {endpoint}")
    
    # Priority 3: Fallback to old-style endpoints if nothing worked
    if not all_matches:
        print("=== No matches found, trying fallback endpoints ===")
        fallback_endpoints = [
            f"/v2.0/{season}/schedule/{event_code}",                 # Basic endpoint for all matches
            f"/v2.0/{season}/schedule/{event_code}?tournamentLevel=all",  # Explicitly request all tournament levels
            f"/v2.0/{season}/scores/{event_code}/all",              # Scores endpoint for all match types
            f"/v2.0/{season}/scores/{event_code}/qual",
        ]
        
        for endpoint in fallback_endpoints:
            api_url = f"{base_url}{endpoint}"
            matches = fetch_from_endpoint(api_url, headers)
            if matches:
                print(f"  Found {len(matches)} matches from fallback {endpoint}")
                all_matches = merge_match_lists(all_matches, matches)
                break  # Stop at first successful fallback
    
    # Check if we got any matches
    if all_matches:
        print(f"=== Total unique matches retrieved: {len(all_matches)} ===")
        return all_matches
    
    # If we get here, all endpoints failed
    print("All API endpoints failed to return match data")
    
    # Check if the event code looks valid
    if not event_code or len(event_code) < 3:
        raise ApiError(f"Invalid event code '{event_code}'. Event codes are typically 4-5 characters (e.g., CALA, NYRO)")
        
    # Check if the season is reasonable (between 2000-2050)
    if season < 2000 or season > 2050:
        raise ApiError(f"Season value ({season}) appears invalid. Check your configuration.")
    
    # Return empty list if no errors but no data - event may just not have matches scheduled yet
    print("No matches found - event may not have matches scheduled yet")
    return []

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
    """Convert API match format to database format
    
    Handles multiple API formats:
    - FIRST API /schedule endpoint: matchNumber, tournamentLevel, teams array, startTime
    - FIRST API /matches endpoint: matchNumber, tournamentLevel, teams array, scoreRedFinal, scoreBlueFinal
    - TBA API format: comp_level, match_number, alliances object
    """
    # Extract match details - handle different field name formats
    match_number = api_match.get('matchNumber') or api_match.get('match_number')
    
    # Get the standardized match type from our helper function
    match_type = get_match_type(api_match)
    
    # Extract teams
    red_alliance = []
    blue_alliance = []
    
    # Handle different API response formats
    if 'teams' in api_match:
        # FIRST API format with teams array (both /schedule and /matches endpoints)
        # Format: [{"teamNumber": 323, "station": "Red1", "surrogate": false}, ...]
        for team in api_match.get('teams', []):
            station = team.get('station', '')
            team_number = team.get('teamNumber')
            
            if team_number:
                if station.startswith('Red'):
                    red_alliance.append(str(team_number))
                elif station.startswith('Blue'):
                    blue_alliance.append(str(team_number))
    elif 'alliances' in api_match:
        # TBA API format with alliances object
        # Format: {"red": {"team_keys": ["frc254", ...]}, "blue": {...}}
        alliances = api_match.get('alliances', {})
        if 'red' in alliances:
            for team in alliances.get('red', {}).get('team_keys', []):
                red_alliance.append(team.replace('frc', ''))
        if 'blue' in alliances:
            for team in alliances.get('blue', {}).get('team_keys', []):
                blue_alliance.append(team.replace('frc', ''))
    
    # Extract scores if available (for completed matches)
    red_score = None
    blue_score = None
    winner = None
    
    # Use shared normalization helper so negative sentinel values (e.g. -1)
    # are treated as None consistently across the codebase
    from app.utils.score_utils import norm_db_score

    # FIRST API uses scoreRedFinal and scoreBlueFinal
    if 'scoreRedFinal' in api_match and 'scoreBlueFinal' in api_match:
        red_score = norm_db_score(api_match.get('scoreRedFinal'))
        blue_score = norm_db_score(api_match.get('scoreBlueFinal'))

        # Determine winner only when both scores are present (non-negative)
        if red_score is not None and blue_score is not None:
            if red_score > blue_score:
                winner = 'red'
            elif blue_score > red_score:
                winner = 'blue'
            else:
                winner = 'tie'
    
    # TBA API uses alliances.red.score and alliances.blue.score
    elif 'alliances' in api_match:
        alliances = api_match.get('alliances', {})
        red_score = norm_db_score(alliances.get('red', {}).get('score'))
        blue_score = norm_db_score(alliances.get('blue', {}).get('score'))

        # Determine winner (TBA uses winning_alliance field, but we can also calculate)
        if red_score is not None and blue_score is not None:
            winning_alliance = api_match.get('winning_alliance', '')
            if winning_alliance == 'red':
                winner = 'red'
            elif winning_alliance == 'blue':
                winner = 'blue'
            elif winning_alliance == '':
                winner = 'tie'
            else:
                # Calculate from scores if winning_alliance not present
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
    
    # Note: scheduled_time is available in API responses (startTime, predicted_time, time)
    # but not currently stored in the Match model. This could be added in a future migration
    # to enable better scheduling features and display of upcoming matches.
    
    return match_data

def get_event_details(event_code):
    """
    Get event details from FIRST API
    Note: FIRST API does not provide timezone directly, so we'll need to infer or get from TBA
    """
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
            first_event = events[0]
            
            # Convert FIRST API format to database format
            # FIRST API provides venue details we can use to infer timezone
            db_format = {
                'name': first_event.get('name', ''),
                'code': first_event.get('code', event_code),
                'location': first_event.get('address', ''),
                'start_date': None,
                'end_date': None,
                'year': season,
                'timezone': None
            }
            
            # Parse dates if available
            if first_event.get('dateStart'):
                try:
                    from datetime import datetime
                    db_format['start_date'] = datetime.fromisoformat(first_event['dateStart'].replace('Z', '+00:00')).date()
                except:
                    pass
            
            if first_event.get('dateEnd'):
                try:
                    from datetime import datetime
                    db_format['end_date'] = datetime.fromisoformat(first_event['dateEnd'].replace('Z', '+00:00')).date()
                except:
                    pass
            
            # Try to infer timezone from FIRST API venue information
            # FIRST API provides: city, stateprov, country in the event object
            city = first_event.get('city')
            state = first_event.get('stateprov')
            country = first_event.get('country')
            
            if city or state or country:
                from app.utils.timezone_utils import infer_timezone_from_location
                inferred_tz = infer_timezone_from_location(city, state, country)
                if inferred_tz:
                    db_format['timezone'] = inferred_tz
                    print(f" Inferred timezone from location ({city}, {state}, {country}): {inferred_tz}")
            
            # If we couldn't infer from FIRST API, try TBA as fallback
            if not db_format['timezone']:
                try:
                    tba_event_key = construct_tba_event_key(event_code, season)
                    tba_event = get_tba_event_details(tba_event_key)
                    if tba_event and tba_event.get('timezone'):
                        db_format['timezone'] = tba_event['timezone']
                        print(f" Got timezone from TBA fallback: {db_format['timezone']}")
                except:
                    print("️  Could not fetch timezone from TBA, will use UTC as default")
            
            return db_format
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
            # Add diagnostic info about where API keys were discovered
            diag = inspect_api_key_locations()
            raise ApiError(f"Both APIs failed. Primary ({preferred_source}): {str(e)}, Fallback ({fallback_source}): {str(fallback_error)}\n\n{diag}")

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

            # If FIRST returned nothing, try TBA fallback immediately (don't wait for exception)
            if not api_matches:
                try:
                    print("FIRST API returned no matches; attempting TBA fallback")
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
                except Exception:
                    # Fall through to convert whatever FIRST returned (likely empty)
                    pass

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
            diag = inspect_api_key_locations()
            raise ApiError(f"Both APIs failed. Primary ({preferred_source}): {str(e)}, Fallback ({fallback_source}): {str(fallback_error)}\n\n{diag}")

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
            diag = inspect_api_key_locations()
            raise ApiError(f"Both APIs failed. Primary ({preferred_source}): {str(e)}, Fallback ({fallback_source}): {str(fallback_error)}\n\n{diag}")