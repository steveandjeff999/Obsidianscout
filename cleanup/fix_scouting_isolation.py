#!/usr/bin/env python3
"""
Quick fix script to replace the remaining unfiltered queries in scouting.py
"""

import re

def fix_scouting_file():
    file_path = "app/routes/scouting.py"
    
    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace Event.query.filter_by(code=current_event_code).first() with get_event_by_code(current_event_code)
    content = re.sub(
        r'Event\.query\.filter_by\(code=current_event_code\)\.first\(\)',
        'get_event_by_code(current_event_code)',
        content
    )
    
    # Replace Match.query.filter_by(event_id=current_event.id).all() with filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).all()
    content = re.sub(
        r'Match\.query\.filter_by\(event_id=current_event\.id\)\.all\(\)',
        'filter_matches_by_scouting_team().filter(Match.event_id == current_event.id).all()',
        content
    )
    
    # Replace Match.query.all() with filter_matches_by_scouting_team().all()
    content = re.sub(
        r'Match\.query\.all\(\)',
        'filter_matches_by_scouting_team().all()',
        content
    )
    
    # Replace current_event.teams with the filtered team query
    content = re.sub(
        r'current_event\.teams',
        'filter_teams_by_scouting_team().join(Team.events).filter(Event.id == current_event.id).order_by(Team.team_number).all()',
        content
    )
    
    # Write the file back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Fixed scouting.py team isolation issues")

if __name__ == '__main__':
    fix_scouting_file()
