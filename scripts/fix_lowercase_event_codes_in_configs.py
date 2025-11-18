"""
Script to fix lowercase event codes in all game_config.json files.

This script scans:
- config/game_config.json (global config)
- instance/configs/*/game_config.json (team-specific configs)

For any config with a lowercase current_event_code, it uppercases it and saves
the file to prevent duplicate events/matches from being created during auto-sync.

Run from the project root:
    python scripts/fix_lowercase_event_codes_in_configs.py
"""

import json
import os
import shutil
from pathlib import Path


def fix_event_code_in_file(config_path):
    """
    Read a config file, uppercase the current_event_code if needed, and save it.
    Returns True if the file was modified, False otherwise.
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if not isinstance(config, dict):
            return False
        
        event_code = config.get('current_event_code')
        if not isinstance(event_code, str):
            return False
        
        # Check if it needs uppercasing
        uppercased = event_code.strip().upper()
        if event_code == uppercased:
            return False
        
        # Make a backup
        backup_path = str(config_path) + '.bak'
        try:
            shutil.copyfile(config_path, backup_path)
            print(f"  Created backup: {backup_path}")
        except Exception as e:
            print(f"  Warning: Could not create backup: {e}")
        
        # Update and save
        config['current_event_code'] = uppercased
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"  ✓ Updated: '{event_code}' → '{uppercased}'")
        return True
        
    except Exception as e:
        print(f"  ✗ Error processing {config_path}: {e}")
        return False


def main():
    """Scan and fix all game_config.json files."""
    print("=" * 60)
    print("Fixing lowercase event codes in config files")
    print("=" * 60)
    
    base_dir = Path.cwd()
    files_checked = 0
    files_modified = 0
    
    # Check global config
    global_config = base_dir / 'config' / 'game_config.json'
    if global_config.exists():
        print(f"\nChecking: {global_config}")
        files_checked += 1
        if fix_event_code_in_file(global_config):
            files_modified += 1
    else:
        print(f"\nSkipping (not found): {global_config}")
    
    # Check team-specific configs
    instance_configs = base_dir / 'instance' / 'configs'
    if instance_configs.exists() and instance_configs.is_dir():
        for team_dir in instance_configs.iterdir():
            if not team_dir.is_dir():
                continue
            
            team_config = team_dir / 'game_config.json'
            if team_config.exists():
                print(f"\nChecking: {team_config}")
                files_checked += 1
                if fix_event_code_in_file(team_config):
                    files_modified += 1
    
    print("\n" + "=" * 60)
    print(f"Summary:")
    print(f"  Files checked:  {files_checked}")
    print(f"  Files modified: {files_modified}")
    print("=" * 60)
    
    if files_modified > 0:
        print("\n✓ Event codes normalized successfully!")
        print("  Backup files (.bak) were created for modified configs.")
    else:
        print("\n✓ All event codes are already uppercase. No changes needed.")


if __name__ == '__main__':
    main()
