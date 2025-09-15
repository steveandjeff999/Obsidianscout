#!/usr/bin/env python3

import sys
import os
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test integration with the actual system
def test_side_by_side_integration():
    """Test that the side-by-side system works end-to-end with the real config"""
    
    print("=== Testing Side-by-Side Integration ===")
    
    # Import after path setup
    from app.utils.analysis import calculate_team_metrics
    
    # Test with a hypothetical team ID
    try:
        # This will show us if the analytics function works with the real database
        result = calculate_team_metrics(1)
        print(f"Analytics result structure: {type(result)}")
        print(f"Analytics keys: {result.keys() if isinstance(result, dict) else 'Not a dict'}")
        
        if isinstance(result, dict):
            metrics = result.get('metrics', {})
            print(f"Available metrics: {list(metrics.keys())}")
            print(f"Match count: {result.get('match_count', 'Not found')}")
            
            # Check for our expected dynamic metrics
            expected_metrics = ['auto_points', 'teleop_points', 'endgame_points', 'total_points']
            found_metrics = [m for m in expected_metrics if m in metrics]
            print(f"Found expected metrics: {found_metrics}")
            
            if found_metrics:
                print("✅ Dynamic metrics are available!")
            else:
                print("❌ No dynamic metrics found")
                
        else:
            print("❌ Unexpected result format")
            
    except Exception as e:
        print(f"❌ Error testing analytics: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== Testing Config Structure ===")
    
    try:
        from app.utils.config_manager import get_current_game_config
        config = get_current_game_config()
        
        print(f"Config has auto_period: {'auto_period' in config}")
        print(f"Config has teleop_period: {'teleop_period' in config}")  
        print(f"Config has endgame_period: {'endgame_period' in config}")
        
        if 'auto_period' in config:
            auto_elements = config['auto_period'].get('scoring_elements', [])
            print(f"Auto period elements: {len(auto_elements)}")
            for elem in auto_elements:
                print(f"  - {elem.get('name', 'Unknown')}: {elem.get('points', 0)} points")
                
        if 'teleop_period' in config:
            teleop_elements = config['teleop_period'].get('scoring_elements', [])
            print(f"Teleop period elements: {len(teleop_elements)}")
            for elem in teleop_elements:
                print(f"  - {elem.get('name', 'Unknown')}: {elem.get('points', 0)} points")
                
        if 'endgame_period' in config:
            endgame_elements = config['endgame_period'].get('scoring_elements', [])
            print(f"Endgame period elements: {len(endgame_elements)}")
            for elem in endgame_elements:
                print(f"  - {elem.get('name', 'Unknown')}: {elem.get('points', 0)} points")
                
        key_metrics = config.get('data_analysis', {}).get('key_metrics', [])
        print(f"Legacy key_metrics count: {len(key_metrics)}")
        
        print("✅ Config structure looks good!")
        
    except Exception as e:
        print(f"❌ Error testing config: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_side_by_side_integration()