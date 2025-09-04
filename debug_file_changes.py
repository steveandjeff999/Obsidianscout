#!/usr/bin/env python3
"""
Debug script to check what files exist before and after updates
"""

import os
from pathlib import Path
import json
from datetime import datetime

def scan_directory_structure(root_path, include_patterns=None):
    """Scan directory and return file information"""
    root = Path(root_path)
    file_info = {}
    
    for item in root.rglob('*'):
        try:
            if item.is_file():
                relative_path = str(item.relative_to(root))
                
                # Filter by patterns if provided
                if include_patterns:
                    if not any(pattern in relative_path.lower() for pattern in include_patterns):
                        continue
                
                stat = item.stat()
                file_info[relative_path] = {
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                    'exists': True
                }
        except (PermissionError, OSError):
            continue
    
    return file_info

def compare_file_states(before, after):
    """Compare two file state dictionaries"""
    all_files = set(before.keys()) | set(after.keys())
    
    changes = {
        'added': [],
        'removed': [],
        'modified': [],
        'unchanged': []
    }
    
    for file_path in sorted(all_files):
        before_info = before.get(file_path)
        after_info = after.get(file_path)
        
        if before_info and not after_info:
            changes['removed'].append(file_path)
        elif not before_info and after_info:
            changes['added'].append(file_path)
        elif before_info and after_info:
            if before_info['size'] != after_info['size'] or before_info['modified'] != after_info['modified']:
                changes['modified'].append(file_path)
            else:
                changes['unchanged'].append(file_path)
    
    return changes

def main():
    root_path = Path(__file__).parent
    
    # Focus on critical files and database files
    include_patterns = ['assistant', '.db', 'core.py', 'visualizer.py', 'models.py', '__init__.py']
    
    print("Scanning current file structure...")
    file_state = scan_directory_structure(root_path, include_patterns)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = root_path / f'file_state_{timestamp}.json'
    
    with open(output_file, 'w') as f:
        json.dump(file_state, f, indent=2)
    
    print(f"File state saved to: {output_file}")
    print(f"Total files scanned: {len(file_state)}")
    
    # Show critical files
    print("\nCritical files found:")
    critical_patterns = ['assistant/core.py', 'assistant/visualizer.py', 'models.py']
    for pattern in critical_patterns:
        matching_files = [f for f in file_state.keys() if pattern in f]
        for f in matching_files:
            print(f"  ✓ {f}")
    
    # Show database files
    print("\nDatabase files found:")
    db_files = [f for f in file_state.keys() if '.db' in f]
    for db_file in sorted(db_files):
        print(f"  ✓ {db_file}")

if __name__ == '__main__':
    main()
