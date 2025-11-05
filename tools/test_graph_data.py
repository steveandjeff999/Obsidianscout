"""
Quick test: verify what data is actually available and test graph API with correct teams
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app import create_app
from app.models import ScoutingData, Team, Match, User
from flask import g

app = create_app()

with app.app_context():
    print("=" * 60)
    print("CHECKING AVAILABLE SCOUTING DATA")
    print("=" * 60)
    
    # Check admin user
    admin = User.query.filter_by(username='admin').first()
    if admin:
        print(f"\nAdmin user: ID={admin.id}, scouting_team_number={admin.scouting_team_number}")
    
    # Find all scouting data for team 5454
    scouting_team = 5454
    print(f"\n\nScouting data BY team {scouting_team}:")
    print("-" * 60)
    
    entries = ScoutingData.query.filter_by(scouting_team_number=scouting_team).all()
    print(f"Found {len(entries)} scouting entries")
    
    # Group by team
    by_team = {}
    for entry in entries:
        team_num = entry.team.team_number if entry.team else None
        if team_num not in by_team:
            by_team[team_num] = []
        by_team[team_num].append(entry)
    
    print(f"\nData exists for {len(by_team)} teams:")
    for team_num in sorted(by_team.keys()):
        count = len(by_team[team_num])
        print(f"  Team {team_num}: {count} match(es)")
        
        # Show first entry details
        first = by_team[team_num][0]
        try:
            auto = first.calculate_metric('apt')
            teleop = first.calculate_metric('tpt')
            endgame = first.calculate_metric('ept')
            total = first.calculate_metric('tot')
            print(f"    Example match {first.match.match_number if first.match else '?'}: auto={auto}, teleop={teleop}, endgame={endgame}, total={total}")
        except Exception as e:
            print(f"    Error calculating metrics: {e}")
    
    print("\n" + "=" * 60)
    print("RECOMMENDED TEAM NUMBERS FOR TESTING:")
    print("=" * 60)
    teams_with_data = sorted(by_team.keys())
    print(f"Teams with data: {teams_with_data}")
    print(f"\nUse these in tinker_graphs_ui.py:")
    print(f"  team_sets = [[{teams_with_data[0]}], {teams_with_data[:3]}]")
