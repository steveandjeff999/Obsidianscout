"""
The Blue Alliance API utilities for the FRC Scouting Platform.
Provides integration with The Blue Alliance API v3.
"""

import requests
import json
import os
from flask import current_app
from datetime import datetime, timezone
from app.utils.config_manager import get_current_game_config, load_game_config
from flask_login import current_user

class TBAApiError(Exception):
    """Exception for TBA API errors"""
    pass

# Global cache for event remap_teams data to avoid repeated API calls
_event_remap_cache = {}

def get_tba_api_key():
    """Get TBA API key from config"""
    # Prefer team-specific instance config when available
    api_key = None
    try:
        team_number = None
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and hasattr(current_user, 'scouting_team_number'):
            team_number = current_user.scouting_team_number

        if team_number:
            game_config = load_game_config(team_number=team_number)
            tba_settings = game_config.get('tba_api_settings', {})
            api_key = tba_settings.get('auth_key')
            if api_key:
                api_key = api_key.strip()
                return api_key
    except Exception:
        # If team lookup fails, fall back to other sources
        api_key = None

    # Next, check environment variable
    api_key = os.environ.get('TBA_API_KEY')
    if api_key and isinstance(api_key, str):
        return api_key.strip()

    # Finally, check global app config
    api_key = current_app.config.get('TBA_API_KEY')
    if isinstance(api_key, str):
        api_key = api_key.strip()

    # As a final fallback, check the loaded game config (useful when running
    # outside a user session or when keys are stored in the game config files)
    try:
        game_config = current_app.config.get('GAME_CONFIG', {})
        tba_settings = game_config.get('tba_api_settings', {})
        cfg_key = tba_settings.get('auth_key')
        if cfg_key and isinstance(cfg_key, str):
            return cfg_key.strip()
    except Exception:
        pass

    # Basic placeholder detection: many default configs use phrases like
    # "your TBA api key here" or similar. Avoid sending obviously placeholder
    # tokens to remote services which will generate confusing 401s.
    try:
        if isinstance(api_key, str):
            low = api_key.lower()
            if any(x in low for x in ('your ', 'your_', 'example', 'replace', 'todo')) or len(api_key.strip()) < 10:
                print("TBA API key looks like a placeholder; ignoring and returning None")
                api_key = None
    except Exception:
        pass

    # If we still don't have a key, try scanning team-specific instance configs
    # for any valid-looking TBA API key and use the first one found. This helps
    # when running without an authenticated user but the repository contains
    # team configs (common during local testing).
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
                            tba_settings = data.get('tba_api_settings', {})
                            k = tba_settings.get('auth_key')
                            if k and isinstance(k, str):
                                lk = k.strip().lower()
                                if not any(x in lk for x in ('your ', 'your_', 'example', 'replace', 'todo')) and len(k.strip()) >= 10:
                                    print(f"Found TBA key in team config {team_folder}; using it as fallback")
                                    return k.strip()
                        except Exception:
                            continue
        except Exception:
            pass

    return api_key

def get_tba_api_headers():
    """Get auth headers for TBA API"""
    api_key = get_tba_api_key()
    
    # If we don't have an API key, use minimal headers 
    if not api_key:
        return {
            'Accept': 'application/json',
            'User-Agent': 'FRC-Scouting-Platform/1.0'
        }
    
    return {
        'Accept': 'application/json',
        'User-Agent': 'FRC-Scouting-Platform/1.0',
        'X-TBA-Auth-Key': api_key
    }

def get_tba_teams_at_event(event_key):
    """Get teams from TBA API for a specific event"""
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    # TBA uses event keys in format like "2025cala" or "2025nyro"
    api_url = f"{base_url}/event/{event_key}/teams"
    
    try:
        print(f"Fetching teams from TBA: {api_url}")
        
        headers = get_tba_api_headers()
        print(f"Using headers: {list(headers.keys())} for TBA teams request")

        response = requests.get(
            api_url,
            headers=headers,
            timeout=15
        )
        
        print(f"TBA teams response status: {response.status_code}")
        
        if response.status_code == 200:
            teams_data = response.json()
            print(f"Successfully fetched {len(teams_data)} teams from TBA")
            return teams_data
        elif response.status_code == 304:
            print("TBA teams data not modified (304)")
            return []
        else:
            # Try to get error message
            try:
                error_data = response.json()
                error_msg = error_data.get('Error', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            if response.status_code == 401:
                print("Authentication failed (401) when contacting TBA API.")
                print(f"Authorization header present: {'X-TBA-Auth-Key' in headers}")
                try:
                    print(f"Response body: {response.text}")
                except Exception:
                    pass

            raise TBAApiError(f"TBA API Error: {error_msg}")
            
    except requests.RequestException as e:
        raise TBAApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise TBAApiError(f"Error getting teams from TBA: {str(e)}")

def get_tba_event_matches(event_key):
    """Get matches from TBA API for a specific event
    
    TBA API includes both scheduled (upcoming) and completed matches in the
    /event/{event_key}/matches endpoint. Matches that haven't been played
    yet will have null values for scores and alliances may be tentative.
    
    According to TBA API docs, this endpoint returns all matches regardless
    of whether they've been played, so it already includes future matches.
    """
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    api_url = f"{base_url}/event/{event_key}/matches"
    
    try:
        print(f"Fetching matches from TBA: {api_url}")
        print("  (TBA includes both scheduled and completed matches)")
        
        headers = get_tba_api_headers()
        print(f"Using headers: {list(headers.keys())} for TBA matches request")

        response = requests.get(
            api_url,
            headers=headers,
            timeout=15
        )
        
        print(f"TBA matches response status: {response.status_code}")
        
        if response.status_code == 200:
            matches_data = response.json()
            
            # Count scheduled vs completed matches for logging
            completed = sum(1 for m in matches_data if m.get('alliances', {}).get('red', {}).get('score', -1) >= 0)
            scheduled = len(matches_data) - completed
            
            print(f"Successfully fetched {len(matches_data)} matches from TBA")
            print(f"  - {completed} completed matches (with scores)")
            print(f"  - {scheduled} scheduled matches (not yet played)")
            
            return matches_data
        elif response.status_code == 304:
            print("TBA matches data not modified (304)")
            return []
        else:
            # Try to get error message
            try:
                error_data = response.json()
                error_msg = error_data.get('Error', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            if response.status_code == 401:
                print("Authentication failed (401) when contacting TBA API for matches.")
                print(f"Authorization header present: {'X-TBA-Auth-Key' in headers}")
                try:
                    print(f"Response body: {response.text}")
                except Exception:
                    pass

            raise TBAApiError(f"TBA API Error: {error_msg}")
            
    except requests.RequestException as e:
        raise TBAApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise TBAApiError(f"Error getting matches from TBA: {str(e)}")

def get_tba_event_details(event_key):
    """Get event details from TBA API"""
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    api_url = f"{base_url}/event/{event_key}"
    
    try:
        print(f"Fetching event details from TBA: {api_url}")
        
        headers = get_tba_api_headers()
        print(f"Using headers: {list(headers.keys())} for TBA event details request")

        response = requests.get(
            api_url,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            event_data = response.json()
            print(f"Successfully fetched event details from TBA: {event_data.get('name', 'Unknown Event')}")
            
            # Cache remap_teams if present (for offseason events with B/C/D teams)
            if 'remap_teams' in event_data and event_data['remap_teams']:
                _event_remap_cache[event_key] = event_data['remap_teams']
                print(f"Cached {len(event_data['remap_teams'])} team remappings for event {event_key}")
            
            return event_data
        elif response.status_code == 304:
            print("TBA event data not modified (304)")
            return None
        else:
            # Try to get error message
            try:
                error_data = response.json()
                error_msg = error_data.get('Error', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            if response.status_code == 401:
                print("Authentication failed (401) when contacting TBA API for event details.")
                print(f"Authorization header present: {'X-TBA-Auth-Key' in headers}")
                try:
                    print(f"Response body: {response.text}")
                except Exception:
                    pass

            raise TBAApiError(f"TBA API Error: {error_msg}")
            
    except requests.RequestException as e:
        raise TBAApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise TBAApiError(f"Error getting event details from TBA: {str(e)}")

def get_event_team_remapping(event_key):
    """Get team remapping dictionary for an event (offseason B/C/D teams)
    
    Returns a dict mapping letter-suffix teams to their 99xx equivalents:
    {'581B': 9989, '1678C': 9996, ...}
    
    The remapping is fetched from TBA's remap_teams field and cached.
    """
    global _event_remap_cache
    
    # Check cache first
    if event_key in _event_remap_cache:
        return _event_remap_cache[event_key]
    
    # Fetch event details to get remap_teams
    try:
        event_data = get_tba_event_details(event_key)
        if event_data and 'remap_teams' in event_data:
            remap = event_data['remap_teams']
            # remap format from TBA: {"frc9989": "frc581B", ...}
            # We need reverse: {"581B": 9989, ...}
            result = {}
            for numeric_key, letter_key in remap.items():
                # Extract numbers: "frc9989" -> 9989, "frc581B" -> "581B"
                numeric_num = numeric_key.replace('frc', '')
                letter_team = letter_key.replace('frc', '')
                try:
                    result[letter_team.upper()] = int(numeric_num)
                except ValueError:
                    pass
            
            _event_remap_cache[event_key] = result
            return result
    except Exception as e:
        print(f"Could not fetch team remapping for {event_key}: {e}")
    
    return {}

def remap_team_number(team_identifier, event_key=None):
    """Remap a team identifier using event's remap_teams if applicable
    
    Args:
        team_identifier: Team number/identifier (int, str, or 'frcXXXX' format)
        event_key: TBA event key (e.g., '2025casj') to lookup remapping
        
    Returns:
        int: Remapped team number if found in remap_teams, otherwise original as int
        
    Examples:
        remap_team_number('581B', '2025casj') -> 9989  (if remap exists)
        remap_team_number('frc1678C', '2025casj') -> 9996  (if remap exists)
        remap_team_number('5454', '2025casj') -> 5454
        remap_team_number(5454, '2025casj') -> 5454
    """
    if team_identifier is None:
        return None
    
    # Convert to string and strip 'frc' prefix if present
    team_str = str(team_identifier).strip()
    if team_str.lower().startswith('frc'):
        team_str = team_str[3:]
    
    if not team_str:
        return None
    
    # Try to convert to int first (normal case)
    try:
        return int(team_str)
    except ValueError:
        # Contains letters - check if we have a remapping for this event
        if event_key:
            remap = get_event_team_remapping(event_key)
            team_upper = team_str.upper()
            if team_upper in remap:
                remapped = remap[team_upper]
                print(f"Remapped team {team_str} -> {remapped} for event {event_key}")
                return remapped
        
        # No remapping found - return original uppercase string
        # (This will cause issues downstream, but at least it's consistent)
        print(f"Warning: Team identifier '{team_str}' contains letters but no remapping found")
        return team_str.upper()

def get_tba_events_by_year(year):
    """Get all events for a specific year from TBA API"""
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    api_url = f"{base_url}/events/{year}"
    
    try:
        print(f"Fetching events from TBA for year {year}: {api_url}")
        
        response = requests.get(
            api_url,
            headers=get_tba_api_headers(),
            timeout=15
        )
        
        print(f"TBA events response status: {response.status_code}")
        
        if response.status_code == 200:
            events_data = response.json()
            print(f"Successfully fetched {len(events_data)} events from TBA")
            return events_data
        elif response.status_code == 304:
            print("TBA events data not modified (304)")
            return []
        else:
            # Try to get error message
            try:
                error_data = response.json()
                error_msg = error_data.get('Error', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            
            raise TBAApiError(f"TBA API Error: {error_msg}")
            
    except requests.RequestException as e:
        raise TBAApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise TBAApiError(f"Error getting events from TBA: {str(e)}")

def tba_team_to_db_format(tba_team, event_key=None):
    """Convert TBA team format to database format
    
    Args:
        tba_team: TBA team data dict
        event_key: Optional TBA event key for team remapping (offseason events)
    """
    team_number = tba_team.get('team_number')
    
    # Handle potential letter-suffix teams (though TBA usually returns numeric)
    if event_key and team_number:
        team_number = remap_team_number(team_number, event_key)
    
    return {
        'team_number': team_number,
        'team_name': tba_team.get('nickname', ''),
        'location': f"{tba_team.get('city', '')}, {tba_team.get('state_prov', '')}, {tba_team.get('country', '')}" .strip(', ')
    }

def tba_match_to_db_format(tba_match, event_id, event_key=None):
    """Convert TBA match format to database format
    
    Args:
        tba_match: TBA match data dict
        event_id: Database event ID
        event_key: Optional TBA event key for team remapping (offseason events)
    """
    # Extract match details
    match_key = tba_match.get('key', '')
    comp_level = tba_match.get('comp_level', '')
    match_number = tba_match.get('match_number', 0)
    set_number = tba_match.get('set_number', 0)
    
    # Extract event_key from match_key if not provided (format: 2025casj_qm1)
    if not event_key and match_key:
        parts = match_key.split('_')
        if parts:
            event_key = parts[0]
    
    # Convert TBA comp_level to our match_type
    match_type_map = {
        'qm': 'Qualification',
        'ef': 'Elimination',
        'qf': 'Quarterfinals',
        'sf': 'Semifinals',
        'f': 'Finals',
        'pr': 'Practice'
    }
    
    match_type = match_type_map.get(comp_level, 'Qualification')
    
    # Extract alliance information
    red_alliance = []
    blue_alliance = []
    
    alliances = tba_match.get('alliances', {})
    
    # Red alliance - remap team numbers for offseason events
    if 'red' in alliances:
        red_teams = alliances['red'].get('team_keys', [])
        for team_key in red_teams:
            team_str = team_key.replace('frc', '')
            remapped = remap_team_number(team_str, event_key)
            red_alliance.append(str(remapped))
    
    # Blue alliance - remap team numbers for offseason events
    if 'blue' in alliances:
        blue_teams = alliances['blue'].get('team_keys', [])
        for team_key in blue_teams:
            team_str = team_key.replace('frc', '')
            remapped = remap_team_number(team_str, event_key)
            blue_alliance.append(str(remapped))
    
    # Extract scores
    red_score = None
    blue_score = None
    winner = None
    
    if 'red' in alliances and 'blue' in alliances:
        red_score = alliances['red'].get('score', None)
        blue_score = alliances['blue'].get('score', None)
        
        # Determine winner
        if red_score is not None and blue_score is not None:
            if red_score > blue_score:
                winner = 'red'
            elif blue_score > red_score:
                winner = 'blue'
            else:
                winner = 'tie'
    
    # For elimination matches, use set number in match number if available
    if comp_level in ['ef', 'qf', 'sf', 'f'] and set_number > 0:
        display_match_number = f"{set_number}-{match_number}"
    else:
        display_match_number = str(match_number)
    
    return {
        'event_id': event_id,
        'match_number': display_match_number,
        'match_type': match_type,
        'red_alliance': ','.join(red_alliance) if red_alliance else '',
        'blue_alliance': ','.join(blue_alliance) if blue_alliance else '',
        'red_score': red_score,
        'blue_score': blue_score,
        'winner': winner
    }

def tba_event_to_db_format(tba_event):
    """Convert TBA event format to database format"""
    # Parse dates
    start_date = None
    end_date = None
    
    if tba_event.get('start_date'):
        try:
            start_date = datetime.strptime(tba_event['start_date'], '%Y-%m-%d').date()
        except ValueError:
            pass
    
    if tba_event.get('end_date'):
        try:
            end_date = datetime.strptime(tba_event['end_date'], '%Y-%m-%d').date()
        except ValueError:
            pass
    
    # Extract location
    location_parts = []
    if tba_event.get('city'):
        location_parts.append(tba_event['city'])
    if tba_event.get('state_prov'):
        location_parts.append(tba_event['state_prov'])
    if tba_event.get('country'):
        location_parts.append(tba_event['country'])
    
    location = ', '.join(location_parts)
    
    # Extract timezone (TBA provides IANA timezone like 'America/Denver')
    event_timezone = tba_event.get('timezone')
    
    return {
        'name': tba_event.get('name', ''),
        'code': tba_event.get('event_code', ''),
        'year': tba_event.get('year', datetime.now(timezone.utc).year),
        'location': location,
        'timezone': event_timezone,
        'start_date': start_date,
        'end_date': end_date
    }

def get_tba_team_events(team_key, year=None):
    """Get events for a specific team from TBA API"""
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    if year:
        api_url = f"{base_url}/team/{team_key}/events/{year}"
    else:
        api_url = f"{base_url}/team/{team_key}/events"
    
    try:
        print(f"Fetching team events from TBA: {api_url}")
        
        response = requests.get(
            api_url,
            headers=get_tba_api_headers(),
            timeout=15
        )
        
        print(f"TBA team events response status: {response.status_code}")
        
        if response.status_code == 200:
            events_data = response.json()
            print(f"Successfully fetched {len(events_data)} events for team {team_key}")
            return events_data
        elif response.status_code == 304:
            print("TBA team events data not modified (304)")
            return []
        else:
            # Try to get error message
            try:
                error_data = response.json()
                error_msg = error_data.get('Error', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            
            raise TBAApiError(f"TBA API Error: {error_msg}")
            
    except requests.RequestException as e:
        raise TBAApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise TBAApiError(f"Error getting team events from TBA: {str(e)}")

def get_tba_team_matches_at_event(team_key, event_key):
    """Get matches for a specific team at a specific event from TBA API"""
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    api_url = f"{base_url}/team/{team_key}/event/{event_key}/matches"
    
    try:
        print(f"Fetching team matches from TBA: {api_url}")
        
        response = requests.get(
            api_url,
            headers=get_tba_api_headers(),
            timeout=15
        )
        
        print(f"TBA team matches response status: {response.status_code}")
        
        if response.status_code == 200:
            matches_data = response.json()
            print(f"Successfully fetched {len(matches_data)} matches for team {team_key} at event {event_key}")
            return matches_data
        elif response.status_code == 304:
            print("TBA team matches data not modified (304)")
            return []
        else:
            # Try to get error message
            try:
                error_data = response.json()
                error_msg = error_data.get('Error', f"HTTP {response.status_code}")
            except:
                error_msg = f"HTTP {response.status_code}"
            
            raise TBAApiError(f"TBA API Error: {error_msg}")
            
    except requests.RequestException as e:
        raise TBAApiError(f"Request failed: {str(e)}")
    except Exception as e:
        raise TBAApiError(f"Error getting team matches from TBA: {str(e)}")

def construct_tba_event_key(event_code, year=None):
    """Construct TBA event key from event code and year"""
    if year is None:
        year = datetime.now(timezone.utc).year
    
    # TBA event keys are lowercase
    return f"{year}{event_code.lower()}"

def construct_tba_team_key(team_number):
    """Construct TBA team key from team number"""
    return f"frc{team_number}"


def get_display_label_for_team(team_identifier, event_key=None):
    """Return a human-friendly display label for a team.

    If an event remapping exists mapping a letter-suffix team (e.g. '581B') to a
    99xx numeric placeholder (e.g. 9989), this helper will return the letter
    suffix (e.g. '581B') when given the numeric placeholder. If no remapping is
    available, it returns the numeric team_identifier as a string.

    Args:
        team_identifier: int or str team number (often 99xx numeric placeholder)
        event_key: optional TBA event key to lookup remap_teams

    Returns:
        str: display label (e.g., '254B' or '9994')
    """
    if team_identifier is None:
        return None

    # Normalize to int when possible
    try:
        num = int(team_identifier)
    except Exception:
        # Not numeric; just return uppercased string
        return str(team_identifier).upper()

    # If event key provided, try to find a letter-suffix mapping that maps to this numeric
    if event_key:
        try:
            # Use get_event_team_remapping which returns mapping letter->numeric
            remap = get_event_team_remapping(event_key)
            # remap: { '581B': 9989, ... }
            for letter, numeric in remap.items():
                if numeric == num:
                    return letter  # letter already uppercased in remapping
        except Exception:
            pass

    # If no mapping found or no event_key, try to inspect cached raw remap data
    try:
        # Some code paths cache the raw remap_teams dict (numeric->letter) in _event_remap_cache
        if event_key in _event_remap_cache and isinstance(_event_remap_cache[event_key], dict):
            # raw may be numeric->letter or letter->numeric; handle both
            cache_val = _event_remap_cache[event_key]
            # numeric->letter
            key = f"frc{num}"
            if key in cache_val:
                return cache_val[key].replace('frc', '').upper()
            # letter->numeric
            for letter, numeric in cache_val.items():
                if isinstance(numeric, int) and numeric == num:
                    return letter
    except Exception:
        pass

    return str(num)
