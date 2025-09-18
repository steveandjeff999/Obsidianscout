#!/usr/bin/env python3
"""
Debug the dynamic calculation methods
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import ScoutingData, Team, db
import json

app = create_app()

with app.app_context():
    print("=== DEBUG: Dynamic Calculation Methods ===\n")
    
    # Get the scouting entry
    entry = ScoutingData.query.first()
    if not entry:
        print("No scouting data found")
        exit(1)
    
    print(f"Entry data: {entry.data}")
    print()
    
    # Get game config
    from app.utils.config_manager import get_current_game_config
    game_config = get_current_game_config()
    
    print("Game config keys:", list(game_config.keys()))
    print("Full game config:", json.dumps(game_config, indent=2)[:500] + "...")
    print()
    
    print("Game config structure:")
    print(f"  auto_period exists: {'auto_period' in game_config}")
    print(f"  teleop_period exists: {'teleop_period' in game_config}")
    print(f"  endgame_period exists: {'endgame_period' in game_config}")
    
    if 'auto_period' in game_config:
        auto_elements = game_config['auto_period'].get('scoring_elements', [])
        print(f"  auto_period.scoring_elements: {len(auto_elements)} elements")
        if auto_elements:
            print(f"    First element: {auto_elements[0]}")
    
    if 'endgame_period' in game_config:
        endgame_elements = game_config['endgame_period'].get('scoring_elements', [])
        print(f"  endgame_period.scoring_elements: {len(endgame_elements)} elements")
        if endgame_elements:
            print(f"    First element: {endgame_elements[0]}")
    print()
    # Test each dynamic calculation method
    local_dict = entry._initialize_data_dict(game_config)
    print(f"Initial local_dict keys: {list(local_dict.keys())}")
    
    # Add actual data to local dict
    from app.utils.config_manager import get_id_to_perm_id_mapping
    id_map = get_id_to_perm_id_mapping()
    for key, value in entry.data.items():
        perm_id = id_map.get(key, key)
        local_dict[perm_id] = value
    
    print(f"Final local_dict sample: {dict(list(local_dict.items())[:10])}")
    print()
    
    # Test each period calculation
    auto_pts = entry._calculate_auto_points_dynamic(local_dict, game_config)
    print(f"Auto points: {auto_pts}")
    
    teleop_pts = entry._calculate_teleop_points_dynamic(local_dict, game_config)
    print(f"Teleop points: {teleop_pts}")
    
    endgame_pts = entry._calculate_endgame_points_dynamic(local_dict, game_config)
    print(f"Endgame points: {endgame_pts}")
    
    total_pts = auto_pts + teleop_pts + endgame_pts
    print(f"Total points: {total_pts}")
    print()
    
    # Let's manually check the auto calculation
    print("=== Manual Auto Calculation ===")
    auto_elements = game_config.get('auto_period', {}).get('scoring_elements', [])
    print(f"Auto elements: {len(auto_elements)}")
    
    for element in auto_elements:
        elem_id = element.get('id')
        perm_id = element.get('perm_id', elem_id)
        points = element.get('points', 0)
        value = local_dict.get(perm_id, local_dict.get(elem_id, 0))
        
        print(f"  {element.get('name', elem_id)}: id={elem_id}, perm_id={perm_id}, value={value}, points={points}")
        
        if elem_id == 'elem_auto_2':
            calculated = value * points if element.get('type') == 'counter' else (points if value else 0)
            print(f"    -> Should contribute: {calculated} points")
    
    print()
    
    # Check endgame calculation
    print("=== Manual Endgame Calculation ===")
    endgame_elements = game_config.get('endgame_period', {}).get('scoring_elements', [])
    print(f"Endgame elements: {len(endgame_elements)}")
    
    for element in endgame_elements:
        elem_id = element.get('id')
        perm_id = element.get('perm_id', elem_id)
        value = local_dict.get(perm_id, local_dict.get(elem_id, ''))
        
        print(f"  {element.get('name', elem_id)}: id={elem_id}, value='{value}', type={element.get('type')}")
        
        if element.get('type') == 'multiple_choice':
            for option in element.get('options', []):
                if option.get('name') == value:
                    print(f"    -> Should contribute: {option.get('points', 0)} points")
                    break