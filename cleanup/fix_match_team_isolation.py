"""
Fix match team isolation by removing duplicate matches across scouting teams.

This script:
1. Identifies duplicate matches (same event_id, match_number, match_type)
2. For each set of duplicates, keeps only one copy per scouting_team_number
3. Removes true duplicates that have the same scouting_team_number

Run this script to clean up the database after team isolation issues.
"""

import sys
import os

# Add the parent directory to the path so we can import from app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Match
from sqlalchemy import func
from collections import defaultdict

def fix_match_isolation():
    """Remove duplicate matches and ensure proper team isolation."""
    app = create_app()
    
    with app.app_context():
        print("Analyzing matches for duplicates...")
        
        # Find all matches grouped by (event_id, match_number, match_type)
        all_matches = Match.query.order_by(Match.event_id, Match.match_type, Match.match_number).all()
        
        # Group matches by unique key
        match_groups = defaultdict(list)
        for match in all_matches:
            key = (match.event_id, match.match_number, match.match_type)
            match_groups[key].append(match)
        
        # Find duplicates
        duplicates_found = []
        for key, matches in match_groups.items():
            if len(matches) > 1:
                duplicates_found.append((key, matches))
        
        if not duplicates_found:
            print("✓ No duplicate matches found!")
            return
        
        print(f"\n Found {len(duplicates_found)} sets of duplicate matches")
        
        # Analyze by scouting team
        team_analysis = defaultdict(int)
        null_team_count = 0
        
        for key, matches in duplicates_found:
            event_id, match_number, match_type = key
            print(f"\n{match_type} Match {match_number} (Event ID: {event_id}):")
            print(f"  Found {len(matches)} copies:")
            
            for match in matches:
                if match.scouting_team_number is None:
                    print(f"    - Match ID {match.id}: scouting_team_number = NULL")
                    null_team_count += 1
                else:
                    print(f"    - Match ID {match.id}: scouting_team_number = {match.scouting_team_number}")
                    team_analysis[match.scouting_team_number] += 1
        
        print(f"\nSummary:")
        print(f"  Matches with NULL scouting_team_number: {null_team_count}")
        for team_num, count in sorted(team_analysis.items()):
            print(f"  Scouting Team {team_num}: {count} matches")
        
        # Ask user what to do
        print("\nOptions:")
        print("1. Keep only matches for a specific scouting team (delete others)")
        print("2. Assign NULL matches to a specific scouting team")
        print("3. Delete all NULL matches")
        print("4. Exit without making changes")
        
        choice = input("\nEnter your choice (1-4): ").strip()
        
        if choice == '1':
            team_num = input("Enter the scouting team number to keep: ").strip()
            try:
                team_num = int(team_num)
            except ValueError:
                print("Invalid team number!")
                return
            
            # Delete matches that don't belong to this team
            deleted_count = 0
            for key, matches in duplicates_found:
                # Keep only the match for the specified team
                for match in matches:
                    if match.scouting_team_number != team_num:
                        print(f"  Deleting Match ID {match.id} (team {match.scouting_team_number})")
                        db.session.delete(match)
                        deleted_count += 1
            
            if deleted_count > 0:
                confirm = input(f"\n This will delete {deleted_count} matches. Confirm? (yes/no): ")
                if confirm.lower() == 'yes':
                    db.session.commit()
                    print(f"✓ Deleted {deleted_count} duplicate matches")
                else:
                    db.session.rollback()
                    print("Cancelled")
            else:
                print("No matches to delete")
        
        elif choice == '2':
            team_num = input("Enter the scouting team number to assign: ").strip()
            try:
                team_num = int(team_num)
            except ValueError:
                print("Invalid team number!")
                return
            
            # Assign NULL matches to this team
            updated_count = 0
            for key, matches in duplicates_found:
                for match in matches:
                    if match.scouting_team_number is None:
                        print(f"  Assigning Match ID {match.id} to team {team_num}")
                        match.scouting_team_number = team_num
                        updated_count += 1
            
            if updated_count > 0:
                confirm = input(f"\n This will update {updated_count} matches. Confirm? (yes/no): ")
                if confirm.lower() == 'yes':
                    db.session.commit()
                    print(f"✓ Updated {updated_count} matches")
                else:
                    db.session.rollback()
                    print("Cancelled")
            else:
                print("No matches to update")
        
        elif choice == '3':
            # Delete all NULL matches
            deleted_count = 0
            for key, matches in duplicates_found:
                for match in matches:
                    if match.scouting_team_number is None:
                        print(f"  Deleting Match ID {match.id} (NULL team)")
                        db.session.delete(match)
                        deleted_count += 1
            
            if deleted_count > 0:
                confirm = input(f"\n This will delete {deleted_count} NULL matches. Confirm? (yes/no): ")
                if confirm.lower() == 'yes':
                    db.session.commit()
                    print(f"✓ Deleted {deleted_count} NULL matches")
                else:
                    db.session.rollback()
                    print("Cancelled")
            else:
                print("No NULL matches to delete")
        
        else:
            print("Exiting without changes")

if __name__ == '__main__':
    fix_match_isolation()
