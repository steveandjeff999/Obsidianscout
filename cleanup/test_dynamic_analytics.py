#!/usr/bin/env python3

import sys
import os
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test the dynamic analytics functionality
from app.models import ScoutingData
from app.utils.config_manager import get_current_game_config

def test_dynamic_analytics():
    """Test that analytics work with a minimal config without key_metrics"""
    
    # Load test config
    with open('test_minimal_config.json', 'r') as f:
        test_config = json.load(f)
    
    print("=== Testing Dynamic Analytics with Minimal Config ===")
    print(f"Config sections: {list(test_config.keys())}")
    print(f"Has data_analysis.key_metrics: {'data_analysis' in test_config and 'key_metrics' in test_config.get('data_analysis', {})}")
    
    # Create a mock ScoutingData object to test the dynamic methods
    scouting_data = ScoutingData()
    
    # Mock data based on the test config elements
    test_data = {
        'auto_speaker_notes': 2,      # 2 notes × 5 points = 10 points
        'teleop_speaker_notes': 5,    # 5 notes × 2 points = 10 points  
        'teleop_amp_notes': 3,        # 3 notes × 1 point = 3 points
        'endgame_climb': True         # True × 3 points = 3 points
    }
    scouting_data.data = test_data
    
    print(f"\nTest data: {test_data}")
    
    # Test the dynamic calculation methods
    auto_points = scouting_data._calculate_auto_points_dynamic(test_data, test_config)
    teleop_points = scouting_data._calculate_teleop_points_dynamic(test_data, test_config)
    endgame_points = scouting_data._calculate_endgame_points_dynamic(test_data, test_config)
    total_points = auto_points + teleop_points + endgame_points
    
    print(f"\nCalculated Points:")
    print(f"  Auto: {auto_points} (expected: 10)")
    print(f"  Teleop: {teleop_points} (expected: 13)")
    print(f"  Endgame: {endgame_points} (expected: 3)")
    print(f"  Total: {total_points} (expected: 26)")
    
    # Verify expected results
    expected_auto = 10    # 2 × 5
    expected_teleop = 13  # (5 × 2) + (3 × 1)
    expected_endgame = 3  # True × 3
    expected_total = 26   # 10 + 13 + 3
    
    success = (
        auto_points == expected_auto and
        teleop_points == expected_teleop and
        endgame_points == expected_endgame and
        total_points == expected_total
    )
    
    print(f"\n=== Test Result: {'PASS' if success else 'FAIL'} ===")
    
    if success:
        print("✅ Dynamic analytics work correctly with minimal config!")
        print("✅ No data_analysis.key_metrics section required!")
    else:
        print("❌ Dynamic analytics calculations don't match expected values")
        
    return success

if __name__ == '__main__':
    test_dynamic_analytics()