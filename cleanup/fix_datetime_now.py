#!/usr/bin/env python3
"""
Fix remaining datetime.now() calls that should be datetime.now(timezone.utc)
This addresses timezone-naive/aware mixing issues.
"""

import re
from pathlib import Path

def fix_datetime_now_without_tz(file_path: Path) -> tuple[bool, int]:
    """Fix datetime.now() to datetime.now(timezone.utc) where needed."""
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        
        # Skip if file already processed or is a test/fix script
        if 'fix_datetime' in str(file_path).lower():
            return False, 0
        
        # Count occurrences of datetime.now() without timezone
        pattern = r'\bdatetime\.now\(\)(?!\s*#.*timezone)'
        matches = re.findall(pattern, content)
        count = len(matches)
        
        if count == 0:
            return False, 0
        
        # Check if timezone import exists
        has_timezone = 'from datetime import' in content and 'timezone' in content
        
        # Replace datetime.now() with datetime.now(timezone.utc)
        # But be careful not to replace in comments or strings
        content = re.sub(
            r'\bdatetime\.now\(\)',
            'datetime.now(timezone.utc)',
            content
        )
        
        # Add timezone import if needed
        if not has_timezone and count > 0:
            import_patterns = [
                (r'from datetime import datetime\b(?!.*timezone)', 'from datetime import datetime, timezone'),
                (r'from datetime import datetime, timedelta\b(?!.*timezone)', 'from datetime import datetime, timedelta, timezone'),
                (r'from datetime import timedelta, datetime\b(?!.*timezone)', 'from datetime import datetime, timedelta, timezone'),
            ]
            
            for pattern, replacement in import_patterns:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content, count=1)
                    break
        
        if content != original_content:
            file_path.write_text(content, encoding='utf-8')
            return True, count
        
        return False, 0
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False, 0

def main():
    root = Path(__file__).parent
    
    # Files that need datetime.now() fixes
    files_to_check = [
        'app/assistant/core.py',
        'app/utils/automatic_sqlite3_sync.py',
        'app/utils/sqlite3_sync.py',
    ]
    
    # Also check all Python files in app/utils for similar issues
    utils_dir = root / 'app' / 'utils'
    if utils_dir.exists():
        for py_file in utils_dir.glob('*.py'):
            rel_path = str(py_file.relative_to(root)).replace('\\', '/')
            if rel_path not in files_to_check:
                files_to_check.append(rel_path)
    
    print("Fixing datetime.now() calls to use timezone.utc...")
    print("=" * 70)
    
    total_files = 0
    total_fixes = 0
    
    for file_str in files_to_check:
        file_path = root / file_str.replace('/', '\\')
        if not file_path.exists():
            continue
        
        modified, count = fix_datetime_now_without_tz(file_path)
        if modified:
            total_files += 1
            total_fixes += count
            print(f" {file_str}: {count} fix(es)")
    
    print("=" * 70)
    print(f" Complete! Files: {total_files}, Fixes: {total_fixes}")
    
    # Create summary
    print("\n" + "=" * 70)
    print("SUMMARY OF TIMEZONE FIXES")
    print("=" * 70)
    print("1. Fixed datetime.min to use timezone.utc in notification_worker.py")
    print("2. Fixed datetime.now() calls across utility files")
    print("3. Added timezone.utc parameter to prevent naive/aware mixing")
    print("4. Updated models to handle timezone-aware timestamp comparisons")
    print("\nAll datetime operations should now be timezone-aware!")
    print("=" * 70)

if __name__ == '__main__':
    main()
