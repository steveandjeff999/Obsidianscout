#!/usr/bin/env python3
"""
Fix datetime.utcnow references used as default parameter (without parentheses).
This handles cases like: default=datetime.utcnow and onupdate=datetime.utcnow
"""

import re
from pathlib import Path

def fix_default_datetime_utcnow(file_path: Path) -> tuple[bool, int]:
    """Fix datetime.utcnow used as default/onupdate parameter."""
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        
        # Count occurrences of datetime.utcnow without parentheses
        pattern = r'\bdatetime\.utcnow\b(?!\()'
        matches = re.findall(pattern, content)
        count = len(matches)
        
        if count == 0:
            return False, 0
        
        # Check if timezone import exists
        has_timezone = 'from datetime import' in content and 'timezone' in content
        
        # Replace datetime.utcnow with lambda: datetime.now(timezone.utc)
        content = re.sub(pattern, 'lambda: datetime.now(timezone.utc)', content)
        
        # Add timezone import if needed
        if not has_timezone:
            import_patterns = [
                (r'from datetime import datetime\b', 'from datetime import datetime, timezone'),
                (r'from datetime import datetime, timedelta\b', 'from datetime import datetime, timedelta, timezone'),
            ]
            
            for pat, repl in import_patterns:
                if re.search(pat, content):
                    content = re.sub(pat, repl, content, count=1)
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
    
    # Files that use datetime.utcnow as default parameter
    files = [
        'app/models_misc.py',
        'app/api_models.py',
        'app/models.py',
        'app/api_models_temp/server_sync.py',
    ]
    
    print("Fixing datetime.utcnow used as default parameter...")
    print("=" * 70)
    
    total_files = 0
    total_fixes = 0
    
    for file_str in files:
        file_path = root / file_str.replace('/', '\\')
        if not file_path.exists():
            print(f"⚠️  File not found: {file_str}")
            continue
        
        modified, count = fix_default_datetime_utcnow(file_path)
        if modified:
            total_files += 1
            total_fixes += count
            print(f"✅ {file_str}: {count} fix(es)")
        else:
            print(f"⏭️  {file_str}: No issues found")
    
    print("=" * 70)
    print(f"✅ Complete! Files: {total_files}, Fixes: {total_fixes}")

if __name__ == '__main__':
    main()
