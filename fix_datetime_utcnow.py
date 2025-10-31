#!/usr/bin/env python3
"""
Comprehensive script to fix all datetime.utcnow() occurrences for Python 3.14 compatibility.
Replaces datetime.utcnow() with datetime.now(timezone.utc) across all Python files.
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple

def fix_file(file_path: Path) -> Tuple[bool, int]:
    """
    Fix datetime.utcnow() occurrences in a single file.
    Returns (was_modified, num_replacements)
    """
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        
        # Count occurrences
        occurrences = content.count('datetime.utcnow()')
        if occurrences == 0:
            return False, 0
        
        # Check if timezone import already exists
        has_timezone_import = 'from datetime import' in content and 'timezone' in content
        
        # Replace datetime.utcnow() with datetime.now(timezone.utc)
        content = content.replace('datetime.utcnow()', 'datetime.now(timezone.utc)')
        
        # Add timezone import if needed and not already present
        if not has_timezone_import and occurrences > 0:
            # Find datetime import line and add timezone
            import_patterns = [
                (r'from datetime import datetime\b', 'from datetime import datetime, timezone'),
                (r'from datetime import datetime, timedelta\b', 'from datetime import datetime, timedelta, timezone'),
                (r'from datetime import timedelta, datetime\b', 'from datetime import datetime, timedelta, timezone'),
            ]
            
            for pattern, replacement in import_patterns:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content, count=1)
                    break
            else:
                # If no match found, try to add timezone to existing datetime import
                datetime_import_match = re.search(r'from datetime import ([^\n]+)', content)
                if datetime_import_match:
                    imports = datetime_import_match.group(1)
                    if 'timezone' not in imports:
                        new_imports = imports.rstrip() + ', timezone'
                        content = content.replace(
                            f'from datetime import {imports}',
                            f'from datetime import {new_imports}',
                            1
                        )
        
        if content != original_content:
            file_path.write_text(content, encoding='utf-8')
            return True, occurrences
        
        return False, 0
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False, 0

def main():
    root = Path(__file__).parent
    
    # List of all files to fix based on the search results
    files_to_fix = [
        'app/api_models.py',
        'app/models_misc.py',
        'app/models.py',
        'app/api_models_temp/server_sync.py',
        'app/routes/api_v1.py',
        'app/routes/assistant.py',
        'app/routes/auth.py',
        'app/routes/data.py',
        'app/routes/db_admin.py',
        'app/routes/graphs.py',
        'app/routes/integrity.py',
        'app/routes/main.py',
        'app/routes/matches.py',
        'app/routes/notifications.py',
        'app/routes/pit_scouting.py',
        'app/routes/realtime_api.py',
        'app/routes/scouting_alliances.py',
        'app/routes/scouting.py',
        'app/routes/sync_api.py',
        'app/routes/teams.py',
        'app/routes/update_monitor.py',
        'app/utils/api_auth.py',
        'app/utils/automatic_sqlite3_sync.py',
        'app/utils/brute_force_protection.py',
        'app/utils/catchup_scheduler.py',
        'app/utils/catchup_sync.py',
        'app/utils/change_tracking.py',
        'app/utils/login_attempt_manager.py',
        'app/utils/multi_server_sync.py',
        'app/utils/notification_service.py',
        'app/utils/notification_worker.py',
        'app/utils/notifications.py',
        'app/utils/push_notifications.py',
        'app/utils/real_time_replication.py',
        'app/utils/simplified_sync.py',
        'app/utils/sync_manager.py',
        'app/utils/sync_utils.py',
        'cleanup/advanced_login_diagnostics.py',
        'cleanup/check_and_force_sync.py',
        'cleanup/check_remote_users.py',
        'cleanup/compare_users.py',
        'cleanup/complete_autonomous_sync_test.py',
        'cleanup/complete_sync_test.py',
        'cleanup/comprehensive_login_fix.py',
        'cleanup/concurrent_examples.py',
        'cleanup/debug_superadmin_login.py',
        'cleanup/debug_sync_connectivity.py',
        'cleanup/debug_user_sync.py',
        'cleanup/disable_heavy_sync.py',
        'cleanup/fast_sync_system.py',
        'cleanup/final_delete_status.py',
        'cleanup/fix_change_tracking_direct.py',
        'cleanup/fix_sync_comprehensive.py',
        'cleanup/live_login_monitor.py',
        'cleanup/manage_login_attempts.py',
        'cleanup/manual_user_sync_test.py',
        'cleanup/realtime_login_check.py',
        'cleanup/repair_sync_system.py',
        'cleanup/simple_login_test.py',
        'cleanup/sync_config_manager.py',
        'cleanup/track_missing_deletions.py',
        'cleanup/verify_sync_status.py',
    ]
    
    total_files = 0
    total_replacements = 0
    errors = []
    
    print("Starting comprehensive datetime.utcnow() fix...")
    print("=" * 70)
    
    for file_path_str in files_to_fix:
        file_path = root / file_path_str.replace('/', '\\')
        
        if not file_path.exists():
            errors.append(f"File not found: {file_path_str}")
            continue
        
        modified, count = fix_file(file_path)
        
        if modified:
            total_files += 1
            total_replacements += count
            print(f" {file_path_str}: {count} replacement(s)")
        elif count == 0:
            print(f" {file_path_str}: No occurrences found")
    
    print("=" * 70)
    print(f"\n Complete!")
    print(f"   Files modified: {total_files}")
    print(f"   Total replacements: {total_replacements}")
    
    if errors:
        print(f"\n️  Errors encountered:")
        for error in errors:
            print(f"   - {error}")
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
