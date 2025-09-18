#!/usr/bin/env python3
"""
Debug the game config loading directly for team 5454
"""

import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import ScoutingData, Team, db
from app.utils.config_manager import load_game_config

app = create_app()

with app.app_context():
    print("=== DEBUG: Game Config Loading ===\n")
    
    # Load config directly for team 5454
    team_config = load_game_config(team_number=5454)
    print("Team 5454 config keys:", list(team_config.keys()) if team_config else "None")
    
    if team_config and 'auto_period' in team_config:
        auto_elements = team_config['auto_period'].get('scoring_elements', [])
        print(f"Auto elements: {len(auto_elements)}")
        
        if auto_elements:
            print("First auto element:", auto_elements[0])
    
    if team_config and 'endgame_period' in team_config:
        endgame_elements = team_config['endgame_period'].get('scoring_elements', [])
        print(f"Endgame elements: {len(endgame_elements)}")
        
        if endgame_elements:
            print("First endgame element:", endgame_elements[0])
    print()
    
    # Now test the calculation using this config directly
    entry = ScoutingData.query.first()
    if entry:
        print(f"Entry data: {entry.data}")
        
        # Test calculation using the loaded config
        local_dict = entry._initialize_data_dict(team_config)
        
        # Add actual data
        from app.utils.config_manager import get_id_to_perm_id_mapping
        id_map = get_id_to_perm_id_mapping()
        for key, value in entry.data.items():
            perm_id = id_map.get(key, key)
            local_dict[perm_id] = value
        
        print("Testing calculations with correct config:")
        auto_pts = entry._calculate_auto_points_dynamic(local_dict, team_config)
        teleop_pts = entry._calculate_teleop_points_dynamic(local_dict, team_config)  
        endgame_pts = entry._calculate_endgame_points_dynamic(local_dict, team_config)
        total_pts = auto_pts + teleop_pts + endgame_pts
        
        print(f"Auto: {auto_pts}, Teleop: {teleop_pts}, Endgame: {endgame_pts}, Total: {total_pts}")
        
        # Manual calculation for verification
        print("\nManual verification:")
        print("elem_auto_2 (CORAL L1):", entry.data.get('elem_auto_2', 0), "* 3 points =", entry.data.get('elem_auto_2', 0) * 3)
        print("elem_endgame_2 (Park):", entry.data.get('elem_endgame_2'), "= 2 points")
        expected_total = (entry.data.get('elem_auto_2', 0) * 3) + 2
        print(f"Expected total: {expected_total}")