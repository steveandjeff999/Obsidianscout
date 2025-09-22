#!/usr/bin/env python3
"""
Fix the duplicate config_reset function in pit_scouting.py
"""

def fix_duplicate_function():
    """Remove the duplicate hardcoded config_reset function"""
    
    file_path = r"c:\Users\steve\OneDrive\Scout2026stuff\5454Scout2026-google-jules\googlejulesobsidianscout\app\routes\pit_scouting.py"
    
    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the duplicate function (second occurrence)
    first_config_reset = None
    second_config_reset = None
    
    for i, line in enumerate(lines):
        if '@bp.route(\'/config/reset\', methods=[\'POST\'])' in line:
            if first_config_reset is None:
                first_config_reset = i
                print(f"First config_reset found at line {i+1}")
            else:
                second_config_reset = i
                print(f"Second config_reset found at line {i+1}")
                break
    
    if second_config_reset is None:
        print("No duplicate function found")
        return False
    
    # Find the end of the second function by looking for the next @bp.route
    end_of_function = None
    for i in range(second_config_reset + 1, len(lines)):
        if lines[i].strip().startswith('@bp.route'):
            end_of_function = i
            print(f"End of duplicate function at line {i+1}")
            break
    
    if end_of_function is None:
        print("Could not find end of duplicate function")
        return False
    
    # Remove the duplicate function
    print(f"Removing lines {second_config_reset+1} to {end_of_function}")
    new_lines = lines[:second_config_reset] + lines[end_of_function:]
    
    # Write the fixed file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"✅ Removed duplicate config_reset function")
    print(f"   Removed {end_of_function - second_config_reset} lines")
    return True

if __name__ == "__main__":
    print("🔧 Fixing duplicate config_reset function...")
    success = fix_duplicate_function()
    
    if success:
        print("✅ Fix completed successfully!")
    else:
        print("❌ Fix failed!")
