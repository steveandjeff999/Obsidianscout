"""
Debug script to trace why graph API shows zeros
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app import create_app, db
from app.models import Team, Event, Match, ScoutingData, User
from app.utils.analysis import calculate_team_metrics
from app.utils.team_isolation import get_current_scouting_team_number
from flask_login import login_user
from flask import g

app = create_app()

with app.app_context():
    print("=" * 80)
    print("COMPREHENSIVE DATA DEBUG")
    print("=" * 80)
    
    # Get the test user
    test_user = User.query.filter_by(username='Seth Herod').first()
    if not test_user:
        print("ERROR: Test user 'Seth Herod' not found!")
        sys.exit(1)
    
    print(f"\n1. TEST USER INFO:")
    print(f"   Username: {test_user.username}")
    print(f"   User ID: {test_user.id}")
    print(f"   Scouting Team Number: {test_user.scouting_team_number}")
    
    scouting_team = test_user.scouting_team_number
    
    # Check events for this scouting team
    print(f"\n2. EVENTS FOR SCOUTING TEAM {scouting_team}:")
    events = Event.query.filter_by(scouting_team_number=scouting_team).all()
    print(f"   Found {len(events)} events")
    for evt in events[:5]:
        print(f"   - Event {evt.id}: {evt.code} - {evt.name}")
    
    # Check teams for this scouting team
    print(f"\n3. TEAMS FOR SCOUTING TEAM {scouting_team}:")
    teams = Team.query.filter_by(scouting_team_number=scouting_team).all()
    print(f"   Found {len(teams)} teams")
    for t in teams[:5]:
        print(f"   - Team {t.id}: #{t.team_number} - {t.team_name}")
    
    # Check scouting data
    print(f"\n4. SCOUTING DATA FOR SCOUTING TEAM {scouting_team}:")
    scouting_entries = ScoutingData.query.filter_by(scouting_team_number=scouting_team).all()
    print(f"   Found {len(scouting_entries)} total scouting entries")
    
    if scouting_entries:
        # Group by team
        by_team = {}
        for entry in scouting_entries:
            team_id = entry.team_id
            if team_id not in by_team:
                by_team[team_id] = []
            by_team[team_id].append(entry)
        
        print(f"   Scouting data exists for {len(by_team)} teams:")
        for team_id, entries in list(by_team.items())[:5]:
            team = Team.query.get(team_id)
            team_num = team.team_number if team else "?"
            print(f"   - Team {team_id} (#{team_num}): {len(entries)} entries")
    
    # Test calculate_team_metrics WITHOUT current_user set
    print(f"\n5. TEST calculate_team_metrics WITHOUT current_user:")
    print(f"   get_current_scouting_team_number() = {get_current_scouting_team_number()}")
    
    if teams:
        test_team = teams[0]
        print(f"   Testing with Team {test_team.id} (#{test_team.team_number})")
        
        # Get the current event
        from app.utils.config_manager import load_game_config
        game_config = load_game_config(team_number=scouting_team)
        event_code = game_config.get('current_event_code') if isinstance(game_config, dict) else None
        event = None
        if event_code:
            event = Event.query.filter_by(code=event_code, scouting_team_number=scouting_team).first()
        if not event and events:
            event = events[0]
        
        event_id = event.id if event else None
        print(f"   Using event_id: {event_id} (code: {event.code if event else 'N/A'})")
        
        result1 = calculate_team_metrics(test_team.id, event_id=event_id)
        print(f"   Result WITHOUT login:")
        print(f"      match_count: {result1.get('match_count')}")
        print(f"      metrics keys: {list(result1.get('metrics', {}).keys())}")
        if result1.get('metrics'):
            print(f"      total_points: {result1['metrics'].get('total_points', 'N/A')}")
            print(f"      auto_points: {result1['metrics'].get('auto_points', 'N/A')}")
    
    # Test WITH current_user set
    print(f"\n6. TEST calculate_team_metrics WITH current_user (login_user):")
    with app.test_request_context():
        login_user(test_user, remember=False)
        print(f"   get_current_scouting_team_number() = {get_current_scouting_team_number()}")
        
        if teams:
            result2 = calculate_team_metrics(test_team.id, event_id=event_id)
            print(f"   Result WITH login:")
            print(f"      match_count: {result2.get('match_count')}")
            print(f"      metrics keys: {list(result2.get('metrics', {}).keys())}")
            if result2.get('metrics'):
                print(f"      total_points: {result2['metrics'].get('total_points', 'N/A')}")
                print(f"      auto_points: {result2['metrics'].get('auto_points', 'N/A')}")
    
    # Direct query to verify data exists
    print(f"\n7. DIRECT QUERY - ScoutingData for team {test_team.id}:")
    direct_query = ScoutingData.query.filter_by(
        team_id=test_team.id,
        scouting_team_number=scouting_team
    )
    if event_id:
        direct_query = direct_query.join(Match).filter(Match.event_id == event_id)
    
    direct_results = direct_query.all()
    print(f"   Found {len(direct_results)} entries")
    
    for entry in direct_results[:3]:
        print(f"   - Entry {entry.id}: Match {entry.match_id}, Data keys: {list(entry.data.keys()) if entry.data else 'None'}")
        if entry.data:
            # Try to calculate points
            try:
                total = entry.data.get('total_points', 0)
                auto = entry.data.get('auto_points', 0)
                print(f"     Raw data: total_points={total}, auto_points={auto}")
            except Exception as e:
                print(f"     Error reading data: {e}")
    
    print("\n" + "=" * 80)
    print("DEBUG COMPLETE")
    print("=" * 80)
