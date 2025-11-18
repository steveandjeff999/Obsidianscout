"""
Fix cross-team event contamination caused by buggy merge_duplicate_events.

This script:
1. Finds events with the same code but different scouting_team_number
2. Moves matches back to the correct team's event based on match.scouting_team_number
3. Verifies team isolation is restored
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Event, Match
from sqlalchemy import func

app = create_app()

def fix_cross_team_contamination():
    """Fix matches that are associated with the wrong team's event."""
    with app.app_context():
        print("=" * 80)
        print("FIXING CROSS-TEAM EVENT CONTAMINATION")
        print("=" * 80)
        
        # Find all event codes that have multiple events (same code, different teams)
        from collections import defaultdict
        code_groups = defaultdict(list)
        
        all_events = Event.query.all()
        for event in all_events:
            if event.code:
                code_groups[event.code.upper()].append(event)
        
        total_moved = 0
        
        for code, events in code_groups.items():
            if len(events) <= 1:
                continue
            
            print(f"\nProcessing event code: {code}")
            print(f"  Found {len(events)} events:")
            for event in events:
                match_count = Match.query.filter_by(event_id=event.id).count()
                print(f"    Event ID {event.id}: scouting_team={event.scouting_team_number}, matches={match_count}")
            
            # For each event, check if it has matches from OTHER teams
            for event in events:
                # Find matches that belong to a DIFFERENT scouting team than the event
                mismatched_matches = Match.query.filter(
                    Match.event_id == event.id,
                    Match.scouting_team_number != event.scouting_team_number
                ).all()
                
                if mismatched_matches:
                    print(f"\n  Event ID {event.id} (team {event.scouting_team_number}) has {len(mismatched_matches)} mismatched matches")
                    
                    # Group mismatched matches by their actual scouting_team_number
                    team_matches = defaultdict(list)
                    for match in mismatched_matches:
                        team_matches[match.scouting_team_number].append(match)
                    
                    # For each team's mismatched matches, find the correct event and move them
                    for team_num, matches in team_matches.items():
                        # Find the event with this code for this team
                        correct_event = next(
                            (e for e in events if e.scouting_team_number == team_num),
                            None
                        )
                        
                        if correct_event:
                            print(f"    Moving {len(matches)} matches from team {team_num} to Event ID {correct_event.id}")
                            for match in matches:
                                match.event_id = correct_event.id
                            total_moved += len(matches)
                        else:
                            print(f"    WARNING: No event found for team {team_num} with code {code}")
                            print(f"             {len(matches)} matches are orphaned!")
        
        if total_moved > 0:
            print(f"\n{'=' * 80}")
            print(f"COMMITTING CHANGES: {total_moved} matches moved to correct events")
            print(f"{'=' * 80}")
            db.session.commit()
            print("✓ Changes committed successfully")
        else:
            print("\n✓ No mismatched matches found - team isolation is correct")
        
        # Final verification
        print(f"\n{'=' * 80}")
        print("FINAL VERIFICATION")
        print(f"{'=' * 80}")
        
        for code, events in code_groups.items():
            if len(events) <= 1:
                continue
            
            print(f"\nEvent code: {code}")
            for event in events:
                match_count = Match.query.filter_by(event_id=event.id).count()
                team_match_count = Match.query.filter_by(
                    event_id=event.id,
                    scouting_team_number=event.scouting_team_number
                ).count()
                mismatch_count = match_count - team_match_count
                
                status = "✓ CORRECT" if mismatch_count == 0 else f"✗ {mismatch_count} MISMATCHED"
                print(f"  Event ID {event.id} (team {event.scouting_team_number}): {match_count} matches [{status}]")

if __name__ == '__main__':
    fix_cross_team_contamination()
