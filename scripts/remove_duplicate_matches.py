"""
Script to remove duplicate matches created due to event code case mismatch.

When event codes were stored in lowercase in config files but uppercase in the database,
the auto-sync could create duplicate matches for the same event.

This script:
1. Finds all duplicate matches (same event_id, match_number, match_type)
2. Keeps the oldest match (earliest created/lowest ID)
3. Deletes the duplicates

Run from the project root with app context:
    python -c "from scripts.remove_duplicate_matches import main; main()"

Or for dry run:
    python -c "from scripts.remove_duplicate_matches import main; import sys; sys.argv.append('--dry-run'); main()"
"""

import sys
import os

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from app import create_app, db
from app.models import Event, Match, ScoutingData
from sqlalchemy import func

def remove_duplicate_matches(dry_run=False):
    """
    Remove duplicate matches, keeping the oldest one for each unique combination.
    """
    app = create_app()
    
    with app.app_context():
        print("=" * 70)
        print("Duplicate Match Removal Tool")
        print("=" * 70)
        
        if dry_run:
            print("\n⚠️  DRY RUN MODE - No changes will be made to the database")
        
        # Find all match groups that have duplicates
        # Group by event_id, match_number, match_type and count
        duplicate_groups = db.session.query(
            Match.event_id,
            Match.match_number,
            Match.match_type,
            func.count(Match.id).label('count')
        ).group_by(
            Match.event_id,
            Match.match_number,
            Match.match_type
        ).having(
            func.count(Match.id) > 1
        ).all()
        
        if not duplicate_groups:
            print("\n✓ No duplicate matches found. Database is clean!")
            return
        
        print(f"\nFound {len(duplicate_groups)} match groups with duplicates")
        
        total_to_delete = 0
        total_kept = 0
        matches_with_scouting_data = 0
        
        # Process each duplicate group
        for event_id, match_number, match_type, count in duplicate_groups:
            # Get all matches in this group, ordered by ID (oldest first)
            matches = Match.query.filter_by(
                event_id=event_id,
                match_number=match_number,
                match_type=match_type
            ).order_by(Match.id).all()
            
            if len(matches) <= 1:
                continue
            
            # Get event info for display
            event = Event.query.get(event_id)
            event_name = f"{event.code} (Team {event.scouting_team_number})" if event else f"Event ID {event_id}"
            
            # Keep the first (oldest) match, delete the rest
            keep_match = matches[0]
            delete_matches = matches[1:]
            
            print(f"\n  {event_name} - {match_type} {match_number}: {len(matches)} duplicates")
            print(f"    Keeping:  Match ID {keep_match.id} (scheduled: {keep_match.scheduled_time})")
            
            for dup_match in delete_matches:
                # Check if this duplicate has any scouting data
                scouting_count = ScoutingData.query.filter_by(match_id=dup_match.id).count()
                
                if scouting_count > 0:
                    print(f"    ⚠️  Match ID {dup_match.id} has {scouting_count} scouting records!")
                    matches_with_scouting_data += 1
                    # We'll still delete it but warn the user
                
                print(f"    Deleting: Match ID {dup_match.id} (scheduled: {dup_match.scheduled_time})")
                
                if not dry_run:
                    # Delete associated scouting data first (due to foreign key constraints)
                    if scouting_count > 0:
                        ScoutingData.query.filter_by(match_id=dup_match.id).delete()
                    
                    db.session.delete(dup_match)
                    total_to_delete += 1
            
            total_kept += 1
        
        print("\n" + "=" * 70)
        print("Summary:")
        print(f"  Match groups processed: {len(duplicate_groups)}")
        print(f"  Matches to keep:        {total_kept}")
        print(f"  Matches to delete:      {total_to_delete}")
        if matches_with_scouting_data > 0:
            print(f"  ⚠️  Matches with scouting data: {matches_with_scouting_data}")
        print("=" * 70)
        
        if not dry_run:
            try:
                db.session.commit()
                print("\n✓ Duplicates removed successfully!")
                print("\nRun the application to verify everything works correctly.")
            except Exception as e:
                db.session.rollback()
                print(f"\n✗ Error: Failed to commit changes: {e}")
                return False
        else:
            print("\n⚠️  Dry run complete. Run without --dry-run to actually delete duplicates.")
        
        return True


def main():
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv
    remove_duplicate_matches(dry_run=dry_run)


if __name__ == '__main__':
    main()
