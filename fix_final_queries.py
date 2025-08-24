#!/usr/bin/env python3
"""
Final fix to replace any remaining Team.query.all() calls
"""

import re
import glob

def fix_remaining_queries():
    """Fix any remaining unfiltered Team/Match/Event queries"""
    
    route_files = glob.glob('app/routes/*.py')
    
    for file_path in route_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Replace standalone Team.query.all() with filter_teams_by_scouting_team().all()
        # But only if it's not already part of a filtered call
        content = re.sub(
            r'(?<!filter_)Team\.query\.all\(\)',
            'filter_teams_by_scouting_team().all()',
            content
        )
        
        # Replace Event.query.filter_by(code=...).first() patterns
        content = re.sub(
            r'Event\.query\.filter_by\(code=[^)]+\)\.first\(\)',
            'get_event_by_code(current_event_code)',
            content
        )
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Applied final fixes to {file_path}")

if __name__ == '__main__':
    fix_remaining_queries()
    print("Final team isolation fixes completed!")
