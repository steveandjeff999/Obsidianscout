"""
Quick diagnostic to check what scouting data exists for the test team.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app
from app.models import Team, Event, ScoutingData, Match
from app.utils.config_manager import load_game_config
from app.utils.analysis import calculate_team_metrics

app = create_app()

with app.app_context():
    # Check for team 5454 (the test team)
    TEAM_NUMBER = 5454
    
    print(f"\n=== Checking data for team {TEAM_NUMBER} ===\n")
    
    # Get the scouting team record
    team_record = Team.query.filter_by(team_number=TEAM_NUMBER).first()
    if team_record:
        print(f"Team found: {team_record.team_name}")
        print(f"  Scouting team number: {team_record.scouting_team_number}")
        print(f"  Team ID: {team_record.id}")
    else:
        print(f"ERROR: Team {TEAM_NUMBER} not found in database!")
        sys.exit(1)
    
    scouting_team_num = team_record.scouting_team_number
    
    # Get current event from game config
    print(f"\n=== Game Config for scouting team {scouting_team_num} ===")
    game_config = load_game_config(team_number=scouting_team_num)
    event_code = game_config.get('current_event_code') if isinstance(game_config, dict) else None
    print(f"Current event code from config: {event_code}")
    
    # Find the event
    event = None
    if event_code:
        event = Event.query.filter_by(code=event_code, scouting_team_number=scouting_team_num).first()
    if not event:
        event = Event.query.filter_by(scouting_team_number=scouting_team_num).order_by(Event.start_date.desc().nullslast(), Event.id.desc()).first()
    
    if event:
        print(f"\nEvent found: {event.name} (code: {event.code}, id: {event.id})")
    else:
        print("\nWARNING: No event found for this scouting team!")
        print("\nAll events in database:")
        all_events = Event.query.all()
        for e in all_events:
            print(f"  - {e.name} (code: {e.code}, id: {e.id}, scouting_team: {e.scouting_team_number})")
    
    event_id = event.id if event else None
    
    # Check for matches
    if event_id:
        print(f"\n=== Matches at event {event.code} ===")
        matches = Match.query.filter_by(
            event_id=event_id,
            scouting_team_number=scouting_team_num
        ).count()
        print(f"Total matches: {matches}")
        
        # Check if team 5454 is in any matches
        team_matches = Match.query.filter_by(
            event_id=event_id,
            scouting_team_number=scouting_team_num
        ).filter(
            (Match.red_alliance.contains(str(TEAM_NUMBER))) | 
            (Match.blue_alliance.contains(str(TEAM_NUMBER)))
        ).all()
        print(f"Matches with team {TEAM_NUMBER}: {len(team_matches)}")
        if team_matches:
            for m in team_matches[:5]:
                print(f"  Match {m.match_number}: Red {m.red_alliance} vs Blue {m.blue_alliance}")
    
    # Check scouting data
    print(f"\n=== Scouting Data ===")
    all_scouting = ScoutingData.query.filter_by(
        team_id=team_record.id,
        scouting_team_number=scouting_team_num
    ).count()
    print(f"Total scouting entries for team {TEAM_NUMBER}: {all_scouting}")
    
    if event_id:
        event_scouting = ScoutingData.query.join(Match).filter(
            ScoutingData.team_id == team_record.id,
            ScoutingData.scouting_team_number == scouting_team_num,
            Match.event_id == event_id
        ).count()
        print(f"Scouting entries for team {TEAM_NUMBER} at event {event.code}: {event_scouting}")
        
        # Get a sample entry
        sample = ScoutingData.query.join(Match).filter(
            ScoutingData.team_id == team_record.id,
            ScoutingData.scouting_team_number == scouting_team_num,
            Match.event_id == event_id
        ).first()
        
        if sample:
            print(f"\nSample scouting entry:")
            print(f"  Match: {sample.match.match_number if sample.match else 'N/A'}")
            print(f"  Data keys: {list(sample.data.keys()) if sample.data else 'N/A'}")
            print(f"  Scout: {sample.scout_name}")
    
    # Calculate metrics
    print(f"\n=== Calculated Metrics (with event_id={event_id}) ===")
    analytics = calculate_team_metrics(team_record.id, event_id=event_id)
    metrics = analytics.get('metrics', {})
    match_count = analytics.get('match_count', 0)
    
    print(f"Match count: {match_count}")
    print(f"Metrics:")
    for key, value in sorted(metrics.items()):
        print(f"  {key}: {value}")
    
    # Also check without event filter
    print(f"\n=== Calculated Metrics (NO event filter) ===")
    analytics_all = calculate_team_metrics(team_record.id, event_id=None)
    metrics_all = analytics_all.get('metrics', {})
    match_count_all = analytics_all.get('match_count', 0)
    
    print(f"Match count: {match_count_all}")
    print(f"Total points: {metrics_all.get('total_points', 0)}")
    print(f"Auto points: {metrics_all.get('auto_points', 0)}")
    
    print("\n=== Done ===\n")
