"""
Check what fields exist in actual scouting data
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app import create_app, db
from app.models import ScoutingData, Team, Match, Event
from app.utils.analysis import calculate_team_metrics

app = create_app()

with app.app_context():
    print("=" * 80)
    print("CHECKING SCOUTING DATA FIELDS")
    print("=" * 80)
    
    # Get scouting data for team 5454
    scouting_team = 5454
    
    print(f"\n1. Finding scouting data for scouting_team_number={scouting_team}")
    entries = ScoutingData.query.filter_by(scouting_team_number=scouting_team).limit(5).all()
    
    print(f"   Found {len(entries)} entries (showing first 5)")
    
    for i, entry in enumerate(entries, 1):
        print(f"\n   Entry {i}:")
        print(f"      ID: {entry.id}")
        print(f"      Team ID: {entry.team_id}")
        team = Team.query.get(entry.team_id)
        if team:
            print(f"      Team: #{team.team_number} - {team.team_name}")
        
        match = Match.query.get(entry.match_id) if entry.match_id else None
        if match:
            print(f"      Match: {match.match_number}")
            print(f"      Event ID: {match.event_id}")
        
        if entry.data:
            print(f"      Data keys ({len(entry.data)} total):")
            for key in sorted(entry.data.keys())[:20]:
                val = entry.data[key]
                print(f"         {key}: {val}")
            if len(entry.data) > 20:
                print(f"         ... and {len(entry.data) - 20} more keys")
            
            # Try to calculate points
            try:
                if hasattr(entry, '_calculate_auto_points_dynamic'):
                    from app.utils.config_manager import load_game_config
                    game_config = load_game_config(team_number=scouting_team)
                    auto = entry._calculate_auto_points_dynamic(entry.data, game_config)
                    teleop = entry._calculate_teleop_points_dynamic(entry.data, game_config)
                    endgame = entry._calculate_endgame_points_dynamic(entry.data, game_config)
                    total = auto + teleop + endgame
                    print(f"      Calculated points: auto={auto}, teleop={teleop}, endgame={endgame}, total={total}")
            except Exception as e:
                print(f"      Error calculating points: {e}")
    
    # Now test calculate_team_metrics
    if entries:
        entry = entries[0]
        team = Team.query.get(entry.team_id)
        if team:
            print(f"\n2. Testing calculate_team_metrics for team {team.team_number} (id={team.id})")
            
            # Get event
            match = Match.query.get(entry.match_id) if entry.match_id else None
            event_id = match.event_id if match else None
            
            print(f"   Event ID: {event_id}")
            
            result = calculate_team_metrics(team.id, event_id=event_id)
            print(f"   Result:")
            print(f"      match_count: {result.get('match_count')}")
            metrics = result.get('metrics', {})
            print(f"      auto_points: {metrics.get('auto_points')}")
            print(f"      teleop_points: {metrics.get('teleop_points')}")
            print(f"      endgame_points: {metrics.get('endgame_points')}")
            print(f"      total_points: {metrics.get('total_points')}")
            
            print(f"\n      All metric keys: {list(metrics.keys())}")
    
    print("\n" + "=" * 80)
