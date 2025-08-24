#!/usr/bin/env python3
"""
Comprehensive fix script to add team isolation to all route files
"""

import re
import os

def fix_route_file(file_path):
    """Fix team isolation issues in a route file"""
    
    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Add team isolation imports if not present
    import_pattern = r'from app\.utils\.team_isolation import'
    if not re.search(import_pattern, content):
        # Find the line after the last import
        imports_end = 0
        for match in re.finditer(r'^from .+ import .+$', content, re.MULTILINE):
            imports_end = match.end()
        
        if imports_end > 0:
            # Insert the team isolation imports after the last import
            import_text = """
from app.utils.team_isolation import (
    filter_teams_by_scouting_team, filter_matches_by_scouting_team, 
    filter_events_by_scouting_team, get_event_by_code
)"""
            content = content[:imports_end] + import_text + content[imports_end:]
    
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
    
    # Replace Event.query.all() with filter_events_by_scouting_team().all()
    content = re.sub(
        r'Event\.query\.all\(\)',
        'filter_events_by_scouting_team().all()',
        content
    )
    
    # Write the file back if changes were made
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed team isolation issues in {file_path}")
        return True
    else:
        print(f"No changes needed in {file_path}")
        return False

def main():
    """Fix all route files"""
    route_files = [
        'app/routes/data.py',
        'app/routes/graphs.py', 
        'app/routes/pit_scouting.py',
        'app/routes/matches.py'
    ]
    
    changes_made = False
    for file_path in route_files:
        if os.path.exists(file_path):
            if fix_route_file(file_path):
                changes_made = True
        else:
            print(f"File not found: {file_path}")
    
    if changes_made:
        print("\nTeam isolation fixes applied successfully!")
    else:
        print("\nNo changes were needed.")

if __name__ == '__main__':
    main()
