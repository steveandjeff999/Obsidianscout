"""
Check scouting team isolation for events and matches.
Verify that teams don't see each other's data even if they use the same event code.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Event, Match
from collections import defaultdict

app = create_app()

with app.app_context():
    print("=" * 70)
    print("Scouting Team Isolation Check")
    print("=" * 70)
    
    # Get all events
    events = Event.query.order_by(Event.code, Event.scouting_team_number).all()
    
    print(f"\nTotal events in database: {len(events)}")
    print("\nAll events:")
    for e in events:
        match_count = Match.query.filter_by(event_id=e.id).count()
        team_str = str(e.scouting_team_number) if e.scouting_team_number is not None else 'None'
        print(f"  ID: {e.id:3d}, Code: {e.code!r:12s}, Team: {team_str:6s}, Matches: {match_count:3d}")
    
    # Group by uppercase event code
    by_code = defaultdict(list)
    for e in events:
        code_upper = e.code.upper() if e.code else None
        by_code[code_upper].append(e)
    
    # Find events with same code but different teams
    print("\n" + "=" * 70)
    print("Events with same code (case-insensitive) but different teams:")
    print("=" * 70)
    
    isolation_issues = []
    for code, evts in sorted(by_code.items()):
        if len(evts) > 1:
            print(f"\nCode: {code}")
            for e in evts:
                match_count = Match.query.filter_by(event_id=e.id).count()
                team_str = str(e.scouting_team_number) if e.scouting_team_number is not None else 'None'
                print(f"  - Event ID {e.id:3d}, Team {team_str:6s}, Matches: {match_count:3d}, Actual Code: {e.code!r}")
            
            # Check if different teams are using the same event
            teams = set(e.scouting_team_number for e in evts)
            if len(teams) > 1:
                isolation_issues.append((code, evts))
                print(f"  ⚠️  ISOLATION ISSUE: {len(teams)} different teams using same event code!")
    
    # Check for matches that might be cross-contaminated
    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    
    if isolation_issues:
        print(f"\n⚠️  Found {len(isolation_issues)} event codes with isolation issues:")
        for code, evts in isolation_issues:
            teams = sorted(set(str(e.scouting_team_number) for e in evts))
            print(f"  - '{code}' used by teams: {', '.join(teams)}")
        
        print("\n🔍 Recommendation:")
        print("  Each scouting team should have their own Event records, even if they're")
        print("  attending the same physical event. The code normalization ensures this")
        print("  works correctly now.")
    else:
        print("\n✓ No isolation issues found!")
        print("  Each scouting team has separate event records.")
    
    # Check team-specific configs
    print("\n" + "=" * 70)
    print("Team config files check:")
    print("=" * 70)
    
    import json
    from pathlib import Path
    
    base_dir = Path.cwd()
    configs_dir = base_dir / 'instance' / 'configs'
    
    if configs_dir.exists():
        for team_dir in sorted(configs_dir.iterdir()):
            if not team_dir.is_dir():
                continue
            
            game_config_file = team_dir / 'game_config.json'
            if game_config_file.exists():
                try:
                    with open(game_config_file, 'r') as f:
                        config = json.load(f)
                    
                    event_code = config.get('current_event_code')
                    if event_code:
                        print(f"  Team {team_dir.name}: event_code = {event_code!r}")
                except Exception as e:
                    print(f"  Team {team_dir.name}: Error reading config - {e}")
