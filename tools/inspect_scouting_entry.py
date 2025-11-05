"""Inspect a scouting entry and print raw data and calculated metrics"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app import create_app
from app.models import ScoutingData
from app.utils.config_manager import load_game_config, get_id_to_perm_id_mapping

app = create_app()

with app.app_context():
    entry = ScoutingData.query.filter_by(scouting_team_number=5454).filter(ScoutingData.team.has(team_number=2583)).first()
    if not entry:
        print("No entries found")
        raise SystemExit

    print(f"Scouting entry id={entry.id} team={entry.team.team_number if entry.team else None} match={entry.match.match_number if entry.match else None}")
    print("Raw data keys:", list(entry.data.keys()))
    print("Raw data:")
    for k, v in entry.data.items():
        print(f"  {k}: {v}")

    for metric in ['tot', 'apt', 'tpt', 'ept']:
        try:
            val = entry.calculate_metric(metric)
        except Exception as e:
            val = f"ERROR: {e}"
        print(f"Metric {metric}: {val}")

    # Build local_dict manually to inspect key values
    game_config = load_game_config(team_number=entry.scouting_team_number)
    local_dict = entry._initialize_data_dict(game_config)
    id_map = get_id_to_perm_id_mapping()
    for key, value in entry.data.items():
        perm_id = id_map.get(key, key)
        local_dict[perm_id] = value

    print("\nLocal dict sample (non-zero/meaningful entries):")
    for k, v in local_dict.items():
        if v not in (0, False, '', None):
            print(f"  {k}: {v}")
