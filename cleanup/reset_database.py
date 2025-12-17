#!/usr/bin/env python3
"""
Database reset script for the FRC Scouting Platform.
This script will delete existing data for the current user's scouting team and recreate it with default data.
Use with caution - this will delete data for your scouting team!
"""

import os
import sys
from app import create_app, db
from app.utils.database_init import initialize_database
from app.models import User, Team, Event, Match, ScoutingData, AllianceSelection, DoNotPickEntry, AvoidEntry, PitScoutingData, StrategyDrawing, AllianceSharedScoutingData, StrategyShare
from flask_login import current_user
from app.utils.team_isolation import get_current_scouting_team_number

def reset_database_for_team():
    """Reset the database data for the current scouting team"""
    print("=" * 60)
    print("TEAM-SPECIFIC DATABASE RESET SCRIPT")
    print("=" * 60)
    
    # Check if user is logged in and has a scouting team
    scouting_team_number = None
    
    # Try to get scouting team from command line argument
    if len(sys.argv) > 1:
        try:
            scouting_team_number = int(sys.argv[1])
            print(f"Using scouting team number from command line: {scouting_team_number}")
        except ValueError:
            print("Invalid scouting team number provided as argument.")
            return
    else:
        print("Please provide a scouting team number as an argument.")
        print("Usage: python reset_database.py <team_number>")
        print("Example: python reset_database.py 5454")
        return
    
    print(f"WARNING: This will delete ALL data for scouting team {scouting_team_number}!")
    print("This includes:")
    print(f"- All teams for scouting team {scouting_team_number}")
    print(f"- All events for scouting team {scouting_team_number}")
    print(f"- All matches for scouting team {scouting_team_number}")
    print(f"- All scouting data for scouting team {scouting_team_number}")
    print(f"- All alliance selections for scouting team {scouting_team_number}")
    print(f"- All pit scouting data for scouting team {scouting_team_number}")
    print("=" * 60)
    
    # Get confirmation
    confirm = input(f"Are you sure you want to reset data for team {scouting_team_number}? (type 'YES' to confirm): ")
    if confirm != 'YES':
        print("Database reset cancelled.")
        return
    
    # Additional confirmation
    confirm2 = input(f"This action cannot be undone for team {scouting_team_number}. Type 'DELETE TEAM DATA' to proceed: ")
    if confirm2 != 'DELETE TEAM DATA':
        print("Database reset cancelled.")
        return
    
    print(f"Proceeding with database reset for scouting team {scouting_team_number}...")
    
    try:
        # Delete scouting data for this team
        scouting_data_count = ScoutingData.query.filter_by(scouting_team_number=scouting_team_number).count()
        ScoutingData.query.filter_by(scouting_team_number=scouting_team_number).delete()
        # Delete alliance-shared copies created by this team
        AllianceSharedScoutingData.query.filter_by(source_scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {scouting_data_count} scouting data entries for team {scouting_team_number}")
        
        # Delete pit scouting data for this team
        pit_data_count = PitScoutingData.query.filter_by(scouting_team_number=scouting_team_number).count()
        PitScoutingData.query.filter_by(scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {pit_data_count} pit scouting data entries for team {scouting_team_number}")
        
        # Delete alliance selections for this team
        alliance_count = AllianceSelection.query.filter_by(scouting_team_number=scouting_team_number).count()
        AllianceSelection.query.filter_by(scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {alliance_count} alliance selections for team {scouting_team_number}")
        
        # Delete do not pick entries for this team
        dnp_count = DoNotPickEntry.query.filter_by(scouting_team_number=scouting_team_number).count()
        DoNotPickEntry.query.filter_by(scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {dnp_count} do not pick entries for team {scouting_team_number}")
        
        # Delete avoid entries for this team
        avoid_count = AvoidEntry.query.filter_by(scouting_team_number=scouting_team_number).count()
        AvoidEntry.query.filter_by(scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {avoid_count} avoid entries for team {scouting_team_number}")
        
        # Delete matches for this team
        # Remove alliance-shared scouting entries referencing these matches first to avoid FK errors
        AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.match.has(Match.scouting_team_number == scouting_team_number)).delete()
        # Remove strategy shares referencing these matches
        StrategyShare.query.filter(StrategyShare.match.has(Match.scouting_team_number == scouting_team_number)).delete()
        match_count = Match.query.filter_by(scouting_team_number=scouting_team_number).count()
        Match.query.filter_by(scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {match_count} matches for team {scouting_team_number}")
        
        # Delete events for this team
        event_count = Event.query.filter_by(scouting_team_number=scouting_team_number).count()
        Event.query.filter_by(scouting_team_number=scouting_team_number).delete()
        print(f"Deleted {event_count} events for team {scouting_team_number}")
        
        # Delete teams for this scouting team (delete dependent rows first)
        teams_to_delete = Team.query.filter_by(scouting_team_number=scouting_team_number).all()
        team_ids = [t.id for t in teams_to_delete]
        team_count = len(team_ids)
        if team_ids:
            # Remove association rows in team_event linking these teams to events
            try:
                db.session.execute(team_event.delete().where(team_event.c.team_id.in_(team_ids)))
            except Exception:
                pass
            # Delete dependent rows referencing these teams
            ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids)).delete()
            PitScoutingData.query.filter(PitScoutingData.team_id.in_(team_ids)).delete()
            AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.team_id.in_(team_ids)).delete()
            AllianceSharedPitData.query.filter(AllianceSharedPitData.team_id.in_(team_ids)).delete()
            TeamListEntry.query.filter(TeamListEntry.team_id.in_(team_ids)).delete()
            # Nullify AllianceSelection fields that reference these teams
            AllianceSelection.query.filter(AllianceSelection.captain.in_(team_ids)).update({AllianceSelection.captain: None})
            AllianceSelection.query.filter(AllianceSelection.first_pick.in_(team_ids)).update({AllianceSelection.first_pick: None})
            AllianceSelection.query.filter(AllianceSelection.second_pick.in_(team_ids)).update({AllianceSelection.second_pick: None})
            AllianceSelection.query.filter(AllianceSelection.third_pick.in_(team_ids)).update({AllianceSelection.third_pick: None})
            # Finally, delete teams
            Team.query.filter(Team.id.in_(team_ids)).delete()
        else:
            team_count = 0
        print(f"Deleted {team_count} teams for scouting team {scouting_team_number}")
        
        # Commit all deletions
        db.session.commit()
        
        print("=" * 60)
        print(f"Database reset complete for scouting team {scouting_team_number}!")
        print("All team-specific data has been deleted.")
        print("Users and global data remain intact.")
        print("=" * 60)
        
    except Exception as e:
        db.session.rollback()
        print(f"Error during database reset: {e}")
        print("Database reset failed. No changes were made.")

def reset_entire_database():
    """Reset the entire database by deleting and recreating it"""
    print("=" * 60)
    print("FULL DATABASE RESET SCRIPT")
    print("=" * 60)
    print("WARNING: This will delete ALL existing data!")
    print("This includes:")
    print("- All users and roles")
    print("- All teams and events")
    print("- All matches and scouting data")
    print("- All configuration settings")
    print("=" * 60)
    
    # Get confirmation
    confirm = input("Are you sure you want to reset the ENTIRE database? (type 'YES' to confirm): ")
    if confirm != 'YES':
        print("Database reset cancelled.")
        return
    
    # Additional confirmation
    confirm2 = input("This action cannot be undone. Type 'DELETE ALL DATA' to proceed: ")
    if confirm2 != 'DELETE ALL DATA':
        print("Database reset cancelled.")
        return
    
    print("Proceeding with FULL database reset...")
    
    # Delete the database file
    db_path = os.path.join('instance', 'scouting.db')
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Deleted database file: {db_path}")
    else:
        print("Database file not found, creating new database...")
    
    # Recreate the database with default data
    print("Creating new database with default data...")
    initialize_database()
    
    print("=" * 60)
    print("Database reset complete!")
    print("Default admin user created:")
    print("  Username: admin")
    print("  Password: password")
    print("=" * 60)
    print("IMPORTANT: Change the admin password after first login!")
    print("=" * 60)

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        # Check if this is a team-specific reset or full reset
        if len(sys.argv) > 1:
            if sys.argv[1] == '--full':
                reset_entire_database()
            else:
                reset_database_for_team()
        else:
            # Default to team-specific reset with help message
            print("Usage:")
            print("  python reset_database.py <team_number>     - Reset data for specific team")
            print("  python reset_database.py --full           - Reset entire database")
            print()
            print("Examples:")
            print("  python reset_database.py 5454")
            print("  python reset_database.py --full")
