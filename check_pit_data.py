"""Quick script to check and fix scouting data with missing scouting_team_number"""
from app import create_app
from app.models import PitScoutingData, AllianceSharedPitData, ScoutingData, db, User
from flask_login import current_user

app = create_app()
with app.app_context():
    # Check PitScoutingData
    pit_data = PitScoutingData.query.all()
    print(f'Total PitScoutingData entries: {len(pit_data)}')
    
    pit_null_entries = [d for d in pit_data if d.scouting_team_number is None]
    print(f'PitScoutingData with NULL scouting_team_number: {len(pit_null_entries)}')
    
    # Check ScoutingData
    scouting_data = ScoutingData.query.all()
    print(f'Total ScoutingData entries: {len(scouting_data)}')
    
    scouting_null_entries = [d for d in scouting_data if d.scouting_team_number is None]
    print(f'ScoutingData with NULL scouting_team_number: {len(scouting_null_entries)}')
    
    # Fix PitScoutingData NULL entries
    if pit_null_entries:
        print()
        print('--- Fixing PitScoutingData NULL entries ---')
        for entry in pit_null_entries:
            if entry.scout_id:
                user = db.session.get(User, entry.scout_id)
                if user and user.scouting_team_number:
                    print(f'Fixing PitScoutingData {entry.id}: setting scouting_team_number to {user.scouting_team_number}')
                    entry.scouting_team_number = user.scouting_team_number
                else:
                    print(f'PitScoutingData {entry.id}: Could not find user or user has no team')
            else:
                print(f'PitScoutingData {entry.id}: No scout_id, cannot determine team')
        db.session.commit()
        print('Done fixing PitScoutingData!')
    
    # Fix ScoutingData NULL entries
    if scouting_null_entries:
        print()
        print('--- Fixing ScoutingData NULL entries ---')
        for entry in scouting_null_entries:
            if entry.scout_id:
                user = db.session.get(User, entry.scout_id)
                if user and user.scouting_team_number:
                    print(f'Fixing ScoutingData {entry.id}: setting scouting_team_number to {user.scouting_team_number}')
                    entry.scouting_team_number = user.scouting_team_number
                else:
                    print(f'ScoutingData {entry.id}: Could not find user or user has no team')
            else:
                print(f'ScoutingData {entry.id}: No scout_id, cannot determine team')
        db.session.commit()
        print('Done fixing ScoutingData!')
    
    print()
    print('=== Final Status ===')
    pit_remaining = PitScoutingData.query.filter(PitScoutingData.scouting_team_number == None).count()
    scouting_remaining = ScoutingData.query.filter(ScoutingData.scouting_team_number == None).count()
    print(f'PitScoutingData with NULL: {pit_remaining}')
    print(f'ScoutingData with NULL: {scouting_remaining}')
