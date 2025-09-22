#!/usr/bin/env python3
"""
Test what happens during the actual file replacement process
"""

import zipfile
import tempfile
import shutil
from pathlib import Path
import json

def analyze_zip_contents(zip_path):
    """Analyze what's in the update ZIP"""
    print(f"Analyzing ZIP contents: {zip_path}")
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        all_files = zf.namelist()
        
        # Look for assistant files
        assistant_files = [f for f in all_files if 'assistant' in f.lower() and f.endswith('.py')]
        print(f"\nAssistant Python files in ZIP:")
        for f in sorted(assistant_files):
            print(f"  {f}")
        
        # Look for database files
        db_files = [f for f in all_files if '.db' in f.lower()]
        print(f"\nDatabase files in ZIP:")
        for f in sorted(db_files):
            print(f"  {f}")
        
        # Look for app directory structure
        app_files = [f for f in all_files if f.startswith('app/') or f.startswith('Obsidian-Scout/app/')]
        print(f"\nApp directory files in ZIP: {len(app_files)} total")
        
        # Check specifically for our problem files
        problem_files = ['core.py', 'visualizer.py']
        for pf in problem_files:
            matching = [f for f in all_files if f.endswith(f'/{pf}') or f.endswith(f'\\{pf}')]
            print(f"\nFiles ending with '{pf}':")
            for f in matching:
                print(f"  {f}")
    
    return all_files

def test_extraction(zip_path):
    """Test extracting the ZIP and see what we get"""
    print(f"\n\nTesting ZIP extraction...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tmpdir_path)
        
        # See what we extracted
        entries = list(tmpdir_path.iterdir())
        print(f"Extracted entries: {[e.name for e in entries]}")
        
        # If there's a single directory, look inside it
        if len(entries) == 1 and entries[0].is_dir():
            release_dir = entries[0]
            print(f"Release directory: {release_dir}")
        else:
            release_dir = tmpdir_path
        
        # Check if assistant files exist in extracted content
        assistant_files = list(release_dir.rglob('*/assistant/*.py'))
        print(f"\nAssistant files found after extraction:")
        for f in assistant_files:
            print(f"  {f.relative_to(release_dir)}")
        
        # Check if specific problem files exist
        core_files = list(release_dir.rglob('**/core.py'))
        visualizer_files = list(release_dir.rglob('**/visualizer.py'))
        
        print(f"\nCore.py files: {[str(f.relative_to(release_dir)) for f in core_files]}")
        print(f"Visualizer.py files: {[str(f.relative_to(release_dir)) for f in visualizer_files]}")

def main():
    # You'll need to provide a recent update ZIP to test
    print("This script needs a ZIP file to analyze.")
    print("Please provide the ZIP file path when running:")
    print("  python debug_update_process.py path/to/update.zip")
    
    import sys
    if len(sys.argv) > 1:
        zip_path = sys.argv[1]
        if Path(zip_path).exists():
            analyze_zip_contents(zip_path)
            test_extraction(zip_path)
        else:
            print(f"ZIP file not found: {zip_path}")
    else:
        print("\nNo ZIP file provided for analysis.")

if __name__ == '__main__':
    main()
