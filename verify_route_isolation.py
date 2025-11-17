#!/usr/bin/env python3
"""
Comprehensive verification of team isolation across all routes.
Checks that routes properly filter data by scouting_team_number.
"""

import os
import re
import ast
from pathlib import Path

# List of route files to check
ROUTE_FILES = [
    'app/routes/alliances.py',
    'app/routes/api_keys.py',
    'app/routes/api_test.py',
    'app/routes/api_v1.py',
    'app/routes/assistant.py',
    'app/routes/auth.py',
    'app/routes/connections.py',
    'app/routes/data.py',
    'app/routes/events.py',
    'app/routes/graphs.py',
    'app/routes/main.py',
    'app/routes/matches.py',
    'app/routes/mobile_api.py',
    'app/routes/notifications.py',
    'app/routes/pit_scouting.py',
    'app/routes/public.py',
    'app/routes/realtime_api.py',
    'app/routes/replication.py',
    'app/routes/replication_api.py',
    'app/routes/scouting.py',
    'app/routes/scouting_alliances.py',
    'app/routes/search.py',
    'app/routes/setup.py',
    'app/routes/sync.py',
    'app/routes/sync_api.py',
    'app/routes/sync_management_new.py',
    'app/routes/teams.py',
    'app/routes/team_data_api.py',
    'app/routes/team_trends.py',
    'app/routes/themes.py',
    'app/routes/trends.py',
]

# Patterns that indicate proper team isolation
ISOLATION_PATTERNS = [
    r'filter_teams_by_scouting_team',
    r'filter_matches_by_scouting_team',
    r'filter_events_by_scouting_team',
    r'filter_scouting_data_by_scouting_team',
    r'filter_users_by_scouting_team',
    r'filter_alliance_selections_by_scouting_team',
    r'filter_do_not_pick_by_scouting_team',
    r'filter_avoid_entries_by_scouting_team',
    r'filter_declined_entries_by_scouting_team',
    r'filter_pit_scouting_data_by_scouting_team',
    r'scouting_team_number\s*==\s*current_user\.scouting_team_number',
    r'filter_by\(scouting_team_number=current_user\.scouting_team_number\)',
    r'\.scouting_team_number\s*==\s*scouting_team',
    r'validate_user_in_same_team',
    r'get_current_scouting_team_number',
    r'@superadmin_required',  # Superadmin routes may bypass isolation
    r'assign_scouting_team_to_model',
]

# Patterns that indicate potential isolation issues
QUERY_PATTERNS = [
    r'Team\.query\.filter',
    r'Match\.query\.filter',
    r'Event\.query\.filter',
    r'ScoutingData\.query\.filter',
    r'User\.query\.filter',
    r'AllianceSelection\.query\.filter',
    r'DoNotPickEntry\.query\.filter',
    r'AvoidEntry\.query\.filter',
    r'PitScoutingData\.query\.filter',
    r'\.query\.all\(\)',
    r'\.query\.first\(\)',
    r'\.query\.get\(',
]

def extract_routes(file_path):
    """Extract route definitions from a Python file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        routes = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '@bp.route(' in line or '@bp.route (' in line:
                # Extract route path
                route_match = re.search(r"@bp\.route\s*\(\s*['\"]([^'\"]+)['\"]", line)
                if route_match:
                    route_path = route_match.group(1)
                    
                    # Find the function name
                    func_name = None
                    for j in range(i + 1, min(i + 10, len(lines))):
                        func_match = re.match(r'def\s+(\w+)\s*\(', lines[j])
                        if func_match:
                            func_name = func_match.group(1)
                            break
                    
                    # Get decorators
                    decorators = []
                    for j in range(max(0, i - 5), i):
                        if '@' in lines[j]:
                            decorators.append(lines[j].strip())
                    
                    routes.append({
                        'path': route_path,
                        'function': func_name,
                        'line': i + 1,
                        'decorators': decorators
                    })
        
        return routes
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []

def check_isolation(file_path):
    """Check if a route file has proper team isolation."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if file imports team isolation utilities
        has_isolation_imports = bool(re.search(r'from app\.utils\.team_isolation import', content))
        
        # Check for isolation patterns
        has_isolation_usage = any(re.search(pattern, content) for pattern in ISOLATION_PATTERNS)
        
        # Check for direct queries that might bypass isolation
        direct_queries = []
        for pattern in QUERY_PATTERNS:
            matches = re.finditer(pattern, content)
            for match in matches:
                # Get context around the match
                start = max(0, match.start() - 200)
                end = min(len(content), match.end() + 200)
                context = content[start:end]
                
                # Check if this query is within an isolated context
                is_isolated = any(re.search(iso_pattern, context) for iso_pattern in ISOLATION_PATTERNS)
                
                if not is_isolated:
                    line_num = content[:match.start()].count('\n') + 1
                    direct_queries.append({
                        'line': line_num,
                        'query': match.group(),
                        'context': context
                    })
        
        return {
            'has_imports': has_isolation_imports,
            'has_usage': has_isolation_usage,
            'direct_queries': direct_queries
        }
    except Exception as e:
        print(f"Error checking {file_path}: {e}")
        return None

def main():
    """Main verification function."""
    print("=" * 80)
    print("TEAM ISOLATION VERIFICATION REPORT")
    print("=" * 80)
    print()
    
    issues_found = []
    files_checked = 0
    
    for route_file in ROUTE_FILES:
        if not os.path.exists(route_file):
            print(f"⚠️  File not found: {route_file}")
            continue
        
        files_checked += 1
        print(f"\n{'=' * 80}")
        print(f"Checking: {route_file}")
        print('=' * 80)
        
        # Extract routes
        routes = extract_routes(route_file)
        print(f"Found {len(routes)} routes")
        
        # Check isolation
        isolation_check = check_isolation(route_file)
        
        if isolation_check:
            print(f"✓ Has isolation imports: {isolation_check['has_imports']}")
            print(f"✓ Uses isolation functions: {isolation_check['has_usage']}")
            
            if isolation_check['direct_queries']:
                print(f"\n⚠️  Found {len(isolation_check['direct_queries'])} potentially unfiltered queries:")
                for query in isolation_check['direct_queries'][:5]:  # Show first 5
                    print(f"  Line {query['line']}: {query['query']}")
                
                issues_found.append({
                    'file': route_file,
                    'queries': isolation_check['direct_queries']
                })
            
            if not isolation_check['has_imports'] and not isolation_check['has_usage']:
                print("\n⚠️  WARNING: No team isolation detected in this file!")
                issues_found.append({
                    'file': route_file,
                    'issue': 'No isolation detected'
                })
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Files checked: {files_checked}")
    print(f"Files with potential issues: {len(issues_found)}")
    
    if issues_found:
        print("\n⚠️  FILES REQUIRING REVIEW:")
        for issue in issues_found:
            print(f"  - {issue['file']}")
            if 'issue' in issue:
                print(f"    {issue['issue']}")
            elif 'queries' in issue:
                print(f"    {len(issue['queries'])} potentially unfiltered queries")
    else:
        print("\n✅ All route files appear to have proper team isolation!")
    
    print("\n" + "=" * 80)

if __name__ == '__main__':
    main()
