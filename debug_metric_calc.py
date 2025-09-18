#!/usr/bin/env python3
"""
Debug the metric calculation issue
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import ScoutingData, Team, db
import json

app = create_app()

with app.app_context():
    print("=== DEBUG: Metric Calculation Issue ===\n")
    
    # Get the scouting entry
    entry = ScoutingData.query.first()
    if not entry:
        print("No scouting data found")
        exit(1)
    
    print(f"Entry ID: {entry.id}")
    print(f"Team ID: {entry.team_id}")
    print(f"Scout: {entry.scout_name}")
    print(f"Data JSON: {entry.data_json}")
    print()
    
    # Try to parse the data
    try:
        data = entry.data
        print(f"Parsed data keys: {list(data.keys())}")
        print(f"Parsed data: {data}")
        print()
    except Exception as e:
        print(f"Error parsing data: {e}")
        exit(1)
    
    # Get game config
    from app.utils.config_manager import get_current_game_config
    game_config = get_current_game_config()
    
    print("Game config key_metrics:")
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            print(f"  - {metric.get('id')}: {metric.get('formula', 'No formula')}")
    else:
        print("  No key_metrics found in game config")
    print()
    
    # Try different metric calculations
    test_metrics = ['tot', 'apt', 'tpt', 'ept']
    
    for metric_id in test_metrics:
        try:
            result = entry.calculate_metric(metric_id)
            print(f"✅ {metric_id}: {result}")
        except Exception as e:
            print(f"❌ {metric_id}: {e}")
    
    print()
    
    # Try to manually calculate if tot formula exists
    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
        for metric in game_config['data_analysis']['key_metrics']:
            if metric.get('id') == 'tot':
                formula = metric.get('formula')
                print(f"Found 'tot' metric with formula: {formula}")
                
                # Try to evaluate manually
                try:
                    # Get the local_dict that would be used
                    local_dict = entry._initialize_data_dict(game_config)
                    
                    # Add actual data
                    from app.utils.config_manager import get_id_to_perm_id_mapping
                    id_map = get_id_to_perm_id_mapping()
                    for key, value in entry.data.items():
                        perm_id = id_map.get(key, key)
                        local_dict[perm_id] = value
                    
                    print(f"Local dict keys: {list(local_dict.keys())}")
                    print(f"Local dict values sample: {dict(list(local_dict.items())[:10])}")
                    
                    # Try to evaluate the formula
                    if formula and formula != "auto_generated":
                        result = eval(formula, {"__builtins__": {}}, local_dict)
                        print(f"✅ Manual formula evaluation: {result}")
                    else:
                        print("Formula is auto_generated or empty")
                        
                except Exception as e:
                    print(f"❌ Manual formula evaluation failed: {e}")
                break