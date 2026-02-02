#!/usr/bin/env python3
"""
Foreign Key Constraint Fix Utility

This script helps diagnose and fix foreign key constraint issues when wiping database data.
It can be run standalone or called from the main application to automatically resolve
foreign key dependency issues.

Usage:
    python fix_foreign_key_constraints.py --team 5454
    python fix_foreign_key_constraints.py --team 5454 --force
    python fix_foreign_key_constraints.py --analyze-only
"""

import argparse
import sys
import os
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import (
    Event, Match, Team, ScoutingData, PitScoutingData, 
    AllianceSelection, TeamListEntry, StrategyDrawing,
    AllianceSharedScoutingData, AllianceSharedPitData,
    SharedGraph, SharedTeamRanks, team_event
)

def analyze_foreign_key_dependencies(scouting_team_number=None):
    """Analyze foreign key dependencies for events and teams"""
    print("=== Foreign Key Dependency Analysis ===")
    
    if scouting_team_number:
        print(f"Analyzing for scouting team: {scouting_team_number}")
        events = Event.query.filter_by(scouting_team_number=scouting_team_number).all()
        teams = Team.query.filter_by(scouting_team_number=scouting_team_number).all()
    else:
        events = Event.query.all()
        teams = Team.query.all()
    
    print(f"\nFound {len(events)} events and {len(teams)} teams to analyze")
    
    # Check event dependencies
    for event in events:
        print(f"\nEvent {event.id} ({event.name}):")
        
        # Check matches
        match_count = Match.query.filter_by(event_id=event.id).count()
        print(f"  - Matches: {match_count}")
        
        # Check team-event associations
        team_event_count = db.session.execute(
            text("SELECT COUNT(*) FROM team_event WHERE event_id = :event_id"),
            {"event_id": event.id}
        ).scalar()
        print(f"  - Team-Event associations: {team_event_count}")
        
        # Check alliance selections
        alliance_count = AllianceSelection.query.filter_by(event_id=event.id).count()
        print(f"  - Alliance selections: {alliance_count}")
        
        # Check pit scouting data
        pit_count = PitScoutingData.query.filter_by(event_id=event.id).count()
        print(f"  - Pit scouting entries: {pit_count}")
        
        # Check team list entries
        team_list_count = TeamListEntry.query.filter_by(event_id=event.id).count()
        print(f"  - Team list entries: {team_list_count}")
        
        # Check shared objects
        shared_graph_count = SharedGraph.query.filter_by(event_id=event.id).count()
        shared_ranks_count = SharedTeamRanks.query.filter_by(event_id=event.id).count()
        print(f"  - Shared graphs: {shared_graph_count}")
        print(f"  - Shared ranks: {shared_ranks_count}")
        
        # Check alliance shared pit data
        alliance_pit_count = AllianceSharedPitData.query.filter_by(event_id=event.id).count()
        print(f"  - Alliance shared pit data: {alliance_pit_count}")
    
    # Check team dependencies
    for team in teams:
        print(f"\nTeam {team.id} ({team.team_number}):")
        
        # Check scouting data
        scouting_count = ScoutingData.query.filter_by(team_id=team.id).count()
        print(f"  - Scouting data entries: {scouting_count}")
        
        # Check pit scouting data
        pit_count = PitScoutingData.query.filter_by(team_id=team.id).count()
        print(f"  - Pit scouting entries: {pit_count}")
        
        # Check alliance selections (as captain, first pick, etc.)
        alliance_as_captain = AllianceSelection.query.filter_by(captain=team.id).count()
        alliance_as_first = AllianceSelection.query.filter_by(first_pick=team.id).count()
        alliance_as_second = AllianceSelection.query.filter_by(second_pick=team.id).count()
        alliance_as_third = AllianceSelection.query.filter_by(third_pick=team.id).count()
        print(f"  - Alliance selections (captain): {alliance_as_captain}")
        print(f"  - Alliance selections (first pick): {alliance_as_first}")
        print(f"  - Alliance selections (second pick): {alliance_as_second}")
        print(f"  - Alliance selections (third pick): {alliance_as_third}")
        
        # Check team list entries
        team_list_count = TeamListEntry.query.filter_by(team_id=team.id).count()
        print(f"  - Team list entries: {team_list_count}")
        
        # Check alliance shared data
        alliance_shared_count = AllianceSharedScoutingData.query.filter_by(team_id=team.id).count()
        alliance_pit_count = AllianceSharedPitData.query.filter_by(team_id=team.id).count()
        print(f"  - Alliance shared scouting: {alliance_shared_count}")
        print(f"  - Alliance shared pit data: {alliance_pit_count}")

def fix_foreign_key_constraints(scouting_team_number, force=False):
    """Fix foreign key constraint issues by cleaning up in proper order"""
    print(f"=== Fixing Foreign Key Constraints for Team {scouting_team_number} ===")
    
    if not force:
        response = input(f"Are you sure you want to delete all data for scouting team {scouting_team_number}? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return False
    
    try:
        # Disable foreign key constraints
        print("Disabling foreign key constraints...")
        db.session.execute(text('PRAGMA foreign_keys = OFF'))
        
        # Get events and teams to delete
        events = Event.query.filter_by(scouting_team_number=scouting_team_number).all()
        teams = Team.query.filter_by(scouting_team_number=scouting_team_number).all()
        event_ids = [e.id for e in events]
        team_ids = [t.id for t in teams]
        
        print(f"Found {len(events)} events and {len(teams)} teams to delete")
        
        if not event_ids and not team_ids:
            print("No data found to delete.")
            return True
        
        # Delete in dependency order
        if event_ids:
            print("Deleting event-related data...")
            
            # 1. Delete team_event associations
            db.session.execute(text('DELETE FROM team_event WHERE event_id IN ({})'.format(','.join(map(str, event_ids)))))
            
            # 2. Delete scouting data for matches in these events
            match_ids = [m.id for m in Match.query.filter(Match.event_id.in_(event_ids)).all()]
            if match_ids:
                ScoutingData.query.filter(ScoutingData.match_id.in_(match_ids)).delete(synchronize_session=False)
                AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.match_id.in_(match_ids)).delete(synchronize_session=False)
            
            # 3. Delete matches
            Match.query.filter(Match.event_id.in_(event_ids)).delete(synchronize_session=False)
            
            # 4. Delete event-scoped records
            TeamListEntry.query.filter(TeamListEntry.event_id.in_(event_ids)).delete(synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.event_id.in_(event_ids)).delete(synchronize_session=False)
            PitScoutingData.query.filter(PitScoutingData.event_id.in_(event_ids)).delete(synchronize_session=False)
            AllianceSharedPitData.query.filter(AllianceSharedPitData.event_id.in_(event_ids)).delete(synchronize_session=False)
            
            # 5. Nullify shared objects
            SharedGraph.query.filter(SharedGraph.event_id.in_(event_ids)).update({SharedGraph.event_id: None}, synchronize_session=False)
            SharedTeamRanks.query.filter(SharedTeamRanks.event_id.in_(event_ids)).update({SharedTeamRanks.event_id: None}, synchronize_session=False)
            
            # 6. Delete events
            Event.query.filter(Event.id.in_(event_ids)).delete(synchronize_session=False)
            print(f"Deleted {len(events)} events")
        
        if team_ids:
            print("Deleting team-related data...")
            
            # 1. Delete team_event associations for these teams
            db.session.execute(text('DELETE FROM team_event WHERE team_id IN ({})'.format(','.join(map(str, team_ids)))))
            
            # 2. Delete scouting data
            ScoutingData.query.filter(ScoutingData.team_id.in_(team_ids)).delete(synchronize_session=False)
            PitScoutingData.query.filter(PitScoutingData.team_id.in_(team_ids)).delete(synchronize_session=False)
            AllianceSharedScoutingData.query.filter(AllianceSharedScoutingData.team_id.in_(team_ids)).delete(synchronize_session=False)
            AllianceSharedPitData.query.filter(AllianceSharedPitData.team_id.in_(team_ids)).delete(synchronize_session=False)
            TeamListEntry.query.filter(TeamListEntry.team_id.in_(team_ids)).delete(synchronize_session=False)
            
            # 3. Nullify alliance selection references
            AllianceSelection.query.filter(AllianceSelection.captain.in_(team_ids)).update({AllianceSelection.captain: None}, synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.first_pick.in_(team_ids)).update({AllianceSelection.first_pick: None}, synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.second_pick.in_(team_ids)).update({AllianceSelection.second_pick: None}, synchronize_session=False)
            AllianceSelection.query.filter(AllianceSelection.third_pick.in_(team_ids)).update({AllianceSelection.third_pick: None}, synchronize_session=False)
            
            # 4. Delete teams
            Team.query.filter(Team.id.in_(team_ids)).delete(synchronize_session=False)
            print(f"Deleted {len(teams)} teams")
        
        # Delete team-scoped data
        print("Deleting team-scoped data...")
        ScoutingData.query.filter_by(scouting_team_number=scouting_team_number).delete()
        PitScoutingData.query.filter_by(scouting_team_number=scouting_team_number).delete()
        StrategyDrawing.query.filter_by(scouting_team_number=scouting_team_number).delete()
        AllianceSelection.query.filter_by(scouting_team_number=scouting_team_number).delete()
        TeamListEntry.query.filter_by(scouting_team_number=scouting_team_number).delete()
        AllianceSharedScoutingData.query.filter_by(source_scouting_team_number=scouting_team_number).delete()
        
        # Re-enable foreign key constraints
        print("Re-enabling foreign key constraints...")
        db.session.execute(text('PRAGMA foreign_keys = ON'))
        
        # Commit all changes
        db.session.commit()
        print("All data deleted successfully!")
        return True
        
    except Exception as e:
        db.session.rollback()
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description='Fix foreign key constraint issues')
    parser.add_argument('--team', type=int, help='Scouting team number to fix')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompts')
    parser.add_argument('--analyze-only', action='store_true', help='Only analyze dependencies, do not delete')
    
    args = parser.parse_args()
    
    app = create_app()
    
    with app.app_context():
        if args.analyze_only:
            analyze_foreign_key_dependencies(args.team)
        elif args.team:
            print(f"Processing team {args.team}")
            analyze_foreign_key_dependencies(args.team)
            
            if not args.analyze_only:
                success = fix_foreign_key_constraints(args.team, args.force)
                if success:
                    print(f"Successfully fixed foreign key constraints for team {args.team}")
                    exit(0)
                else:
                    print(f"Failed to fix foreign key constraints for team {args.team}")
                    exit(1)
        else:
            print("Usage: python fix_foreign_key_constraints.py --team <team_number> [--force] [--analyze-only]")
            exit(1)

if __name__ == "__main__":
    main()