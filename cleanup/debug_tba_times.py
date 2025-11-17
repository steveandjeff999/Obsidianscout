"""
Debug script to see what TBA API actually returns for match times
"""
import requests
from app import create_app
from app.utils.tba_api_utils import get_tba_api_headers, construct_tba_event_key
from app.utils.config_manager import get_current_game_config

app = create_app()

with app.app_context():
    # Get current event
    config = get_current_game_config()
    event_code = config.get('current_event_code', 'oktu')
    year = config.get('season', 2025)
    
    # Construct TBA event key
    event_key = construct_tba_event_key(event_code, year)
    
    print(f"Fetching matches for TBA event key: {event_key}")
    print("=" * 80)
    
    base_url = 'https://www.thebluealliance.com/api/v3'
    api_url = f"{base_url}/event/{event_key}/matches"
    
    try:
        response = requests.get(api_url, headers=get_tba_api_headers(), timeout=15)
        
        print(f"Status code: {response.status_code}\n")
        
        if response.status_code == 200:
            matches = response.json()
            print(f"Found {len(matches)} matches\n")
            
            # Show first few matches
            for i, match in enumerate(matches[:5]):
                print(f"\n--- Match {i+1} ---")
                print(f"Key: {match.get('key')}")
                print(f"Match number: {match.get('match_number')}")
                print(f"Comp level: {match.get('comp_level')}")
                print(f"Actual time: {match.get('actual_time')} (Unix timestamp)")
                print(f"Predicted time: {match.get('predicted_time')} (Unix timestamp)")
                print(f"Time: {match.get('time')} (Unix timestamp)")
                print(f"Post result time: {match.get('post_result_time')}")
                
                # Convert to datetime if available
                if match.get('actual_time'):
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(match.get('actual_time'), tz=timezone.utc)
                    print(f"  -> Actual time as datetime: {dt}")
                
                if match.get('predicted_time'):
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(match.get('predicted_time'), tz=timezone.utc)
                    print(f"  -> Predicted time as datetime: {dt}")
                
                if match.get('time'):
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(match.get('time'), tz=timezone.utc)
                    print(f"  -> Time as datetime: {dt}")
        else:
            print(f"Error response: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")
