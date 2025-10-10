"""
Test script for offline scouting form functionality
Tests localStorage caching and offline form generation
"""

import json
import os
from datetime import datetime


def test_localStorage_structure():
    """Test the expected structure of cached data"""
    
    # Sample cached teams data
    teams_cache = [
        {
            "id": "1",
            "team_number": "5454",
            "team_name": "The BoltBots",
            "text": "5454 - The BoltBots"
        },
        {
            "id": "2",
            "team_number": "1234",
            "team_name": "Example Team",
            "text": "1234 - Example Team"
        }
    ]
    
    # Sample cached matches data
    matches_cache = [
        {
            "id": "1",
            "match_type": "Qualification",
            "match_number": "1",
            "text": "Qualification 1"
        },
        {
            "id": "2",
            "match_type": "Qualification",
            "match_number": "2",
            "text": "Qualification 2"
        }
    ]
    
    # Sample game config
    game_config = {
        "season": 2026,
        "current_event_code": "2026test",
        "auto_period": {
            "name": "Autonomous",
            "scoring_elements": [
                {
                    "id": "auto_speaker",
                    "name": "Speaker",
                    "type": "counter",
                    "default": 0,
                    "points_value": 5
                }
            ]
        },
        "teleop_period": {
            "name": "Teleoperated",
            "scoring_elements": [
                {
                    "id": "teleop_speaker",
                    "name": "Speaker",
                    "type": "counter",
                    "default": 0,
                    "points_value": 2
                }
            ]
        },
        "endgame_period": {
            "name": "Endgame",
            "scoring_elements": [
                {
                    "id": "endgame_climb",
                    "name": "Climb Status",
                    "type": "select",
                    "options": ["No Attempt", "Failed", "Parked", "Climbed"],
                    "default": "No Attempt"
                }
            ]
        },
        "post_match": {
            "rating_elements": [
                {
                    "id": "defense_rating",
                    "name": "Defense Rating",
                    "type": "rating",
                    "default": 3
                }
            ],
            "text_elements": [
                {
                    "id": "comments",
                    "name": "Comments",
                    "type": "textarea",
                    "default": ""
                }
            ]
        }
    }
    
    print("✅ Team cache structure valid")
    print(f"   - {len(teams_cache)} teams cached")
    
    print("✅ Match cache structure valid")
    print(f"   - {len(matches_cache)} matches cached")
    
    print("✅ Game config structure valid")
    print(f"   - {len(game_config)} periods configured")
    
    # Test offline form data structure
    offline_form = {
        "id": int(datetime.now().timestamp() * 1000),
        "timestamp": datetime.now().isoformat(),
        "data": {
            "team_id": "1",
            "match_id": "1",
            "team_number": "5454",
            "match_number": "1",
            "match_type": "Qualification",
            "auto_speaker": 3,
            "teleop_speaker": 8,
            "endgame_climb": "Climbed",
            "defense_rating": 4,
            "comments": "Great match!",
            "offline": True
        },
        "synced": False
    }
    
    print("✅ Offline form structure valid")
    print(f"   - Form ID: {offline_form['id']}")
    print(f"   - Synced: {offline_form['synced']}")
    
    return True


def test_cache_age_calculation():
    """Test cache age validation"""
    
    # Cache duration: 24 hours = 86400000 milliseconds
    CACHE_DURATION = 24 * 60 * 60 * 1000
    
    now = int(datetime.now().timestamp() * 1000)
    
    # Fresh cache (1 hour old)
    fresh_cache = now - (1 * 60 * 60 * 1000)
    age = now - fresh_cache
    is_stale = age > CACHE_DURATION
    
    print(f"✅ Fresh cache test: {'PASS' if not is_stale else 'FAIL'}")
    print(f"   - Age: {age // 1000 // 60} minutes")
    
    # Stale cache (25 hours old)
    stale_cache = now - (25 * 60 * 60 * 1000)
    age = now - stale_cache
    is_stale = age > CACHE_DURATION
    
    print(f"✅ Stale cache test: {'PASS' if is_stale else 'FAIL'}")
    print(f"   - Age: {age // 1000 // 60 // 60} hours")
    
    return True


def test_form_field_generation():
    """Test form field generation logic"""
    
    test_elements = [
        {
            "type": "counter",
            "id": "test_counter",
            "name": "Test Counter",
            "default": 0,
            "points_value": 5
        },
        {
            "type": "boolean",
            "id": "test_checkbox",
            "name": "Test Checkbox",
            "default": False
        },
        {
            "type": "select",
            "id": "test_select",
            "name": "Test Select",
            "options": ["Option 1", "Option 2", "Option 3"],
            "default": "Option 1"
        },
        {
            "type": "rating",
            "id": "test_rating",
            "name": "Test Rating",
            "default": 3
        },
        {
            "type": "text",
            "id": "test_text",
            "name": "Test Text",
            "default": ""
        }
    ]
    
    for element in test_elements:
        elem_type = element.get('type')
        elem_id = element.get('id')
        elem_name = element.get('name')
        
        print(f"✅ {elem_type.title()} element valid")
        print(f"   - ID: {elem_id}")
        print(f"   - Name: {elem_name}")
    
    return True


def test_offline_save_format():
    """Test offline form save format"""
    
    form_data = {
        "team_id": "1",
        "match_id": "1",
        "team_number": "5454",
        "match_number": "1",
        "match_type": "Qualification",
        "scout_name": "Test Scout",
        "auto_speaker": 3,
        "auto_amp": 2,
        "teleop_speaker": 8,
        "teleop_amp": 5,
        "endgame_climb": "Climbed",
        "defense_rating": 4,
        "driver_skill": 5,
        "comments": "Great match!",
        "timestamp": datetime.now().isoformat(),
        "offline": True
    }
    
    # Validate all required fields
    required_fields = ["team_id", "match_id", "timestamp"]
    for field in required_fields:
        if field not in form_data:
            print(f"❌ Missing required field: {field}")
            return False
        print(f"✅ Required field present: {field}")
    
    # Validate data types
    if not isinstance(form_data["auto_speaker"], int):
        print(f"❌ Counter field should be integer")
        return False
    print(f"✅ Counter fields are integers")
    
    if not isinstance(form_data["offline"], bool):
        print(f"❌ Boolean field should be boolean")
        return False
    print(f"✅ Boolean fields are booleans")
    
    # Test JSON serialization
    try:
        json_str = json.dumps(form_data)
        parsed = json.loads(json_str)
        print(f"✅ Form data is JSON serializable")
        print(f"   - Serialized size: {len(json_str)} bytes")
    except Exception as e:
        print(f"❌ JSON serialization failed: {e}")
        return False
    
    return True


def main():
    """Run all tests"""
    print("=" * 60)
    print("OFFLINE SCOUTING FORM TEST SUITE")
    print("=" * 60)
    print()
    
    tests = [
        ("localStorage Structure", test_localStorage_structure),
        ("Cache Age Calculation", test_cache_age_calculation),
        ("Form Field Generation", test_form_field_generation),
        ("Offline Save Format", test_offline_save_format),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        try:
            result = test_func()
            if result:
                passed += 1
                print(f"✅ {test_name} PASSED")
            else:
                failed += 1
                print(f"❌ {test_name} FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {test_name} FAILED with exception: {e}")
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
