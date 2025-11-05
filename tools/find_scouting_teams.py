"""
Find which scouting teams have data
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from app import create_app, db
from app.models import Team, Event, Match, ScoutingData, User
from sqlalchemy import func

app = create_app()

with app.app_context():
    print("=" * 80)
    print("FINDING SCOUTING TEAMS WITH DATA")
    print("=" * 80)
    
    # Find all scouting team numbers with data
    print("\n1. Users and their scouting teams:")
    users = User.query.filter(User.scouting_team_number.isnot(None)).all()
    for u in users[:10]:
        print(f"   User: {u.username} -> scouting_team_number: {u.scouting_team_number}")
    
    print("\n2. Scouting team numbers with Teams:")
    team_counts = db.session.query(
        Team.scouting_team_number, 
        func.count(Team.id)
    ).group_by(Team.scouting_team_number).all()
    
    for stn, count in team_counts:
        print(f"   Scouting team {stn}: {count} teams")
    
    print("\n3. Scouting team numbers with Events:")
    event_counts = db.session.query(
        Event.scouting_team_number,
        func.count(Event.id)
    ).group_by(Event.scouting_team_number).all()
    
    for stn, count in event_counts:
        print(f"   Scouting team {stn}: {count} events")
    
    print("\n4. Scouting team numbers with ScoutingData:")
    scouting_counts = db.session.query(
        ScoutingData.scouting_team_number,
        func.count(ScoutingData.id)
    ).group_by(ScoutingData.scouting_team_number).all()
    
    for stn, count in scouting_counts:
        print(f"   Scouting team {stn}: {count} scouting entries")
    
    print("\n5. Sample data for each scouting team with entries:")
    for stn, _ in scouting_counts[:3]:
        print(f"\n   Scouting Team {stn}:")
        
        # Get one team
        team = Team.query.filter_by(scouting_team_number=stn).first()
        if team:
            print(f"      Sample team: #{team.team_number} - {team.team_name}")
        
        # Get one event
        event = Event.query.filter_by(scouting_team_number=stn).first()
        if event:
            print(f"      Sample event: {event.code} - {event.name}")
        
        # Get one scouting entry
        entry = ScoutingData.query.filter_by(scouting_team_number=stn).first()
        if entry:
            print(f"      Sample scouting entry: ID {entry.id}, Team {entry.team_id}, Match {entry.match_id}")
            if entry.data:
                print(f"      Data keys: {list(entry.data.keys())[:10]}")
    
    print("\n" + "=" * 80)
