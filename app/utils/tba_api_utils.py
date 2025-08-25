"""
The Blue Alliance API utilities for the FRC Scouting Platform.
Provides integration with The Blue Alliance API v3.
"""

import requests
import json
import os
from flask import current_app
from datetime import datetime
from app.utils.config_manager import get_current_game_config, load_game_config
from flask_login import current_user

class TBAApiError(Exception):
    """Exception for TBA API errors"""
    pass

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
    """Get matches from TBA API for a specific event"""
    base_url = 'https://www.thebluealliance.com/api/v3'
    
    api_url = f"{base_url}/event/{event_key}/matches"
    
    try:
        print(f"Fetching matches from TBA: {api_url}")
        
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
            print(f"Successfully fetched {len(matches_data)} matches from TBA")
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

def tba_team_to_db_format(tba_team):
    """Convert TBA team format to database format"""
    return {
        'team_number': tba_team.get('team_number'),
        'team_name': tba_team.get('nickname', ''),
        'location': f"{tba_team.get('city', '')}, {tba_team.get('state_prov', '')}, {tba_team.get('country', '')}".strip(', ')
    }

def tba_match_to_db_format(tba_match, event_id):
    """Convert TBA match format to database format"""
    # Extract match details
    match_key = tba_match.get('key', '')
    comp_level = tba_match.get('comp_level', '')
    match_number = tba_match.get('match_number', 0)
    set_number = tba_match.get('set_number', 0)
    
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
    
    # Red alliance
    if 'red' in alliances:
        red_teams = alliances['red'].get('team_keys', [])
        red_alliance = [team.replace('frc', '') for team in red_teams]
    
    # Blue alliance
    if 'blue' in alliances:
        blue_teams = alliances['blue'].get('team_keys', [])
        blue_alliance = [team.replace('frc', '') for team in blue_teams]
    
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
    
    return {
        'name': tba_event.get('name', ''),
        'code': tba_event.get('event_code', ''),
        'year': tba_event.get('year', datetime.now().year),
        'location': location,
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
        year = datetime.now().year
    
    # TBA event keys are lowercase
    return f"{year}{event_code.lower()}"

def construct_tba_team_key(team_number):
    """Construct TBA team key from team number"""
    return f"frc{team_number}"
