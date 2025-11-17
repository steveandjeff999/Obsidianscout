"""
Test script to verify the access denied fix works correctly.
Run this with: python test_directory_fix.py
"""

import os
import sys
import tempfile

print("=" * 60)
print("Testing Directory Access Fix")
print("=" * 60)
print()

# Test 1: Check current directory
print("Test 1: Current Directory Check")
print(f"  Current directory: {os.getcwd()}")
script_dir = os.path.dirname(os.path.abspath(__file__))
print(f"  Script directory: {script_dir}")
print(f"  Match: {'✓' if os.getcwd() == script_dir else '✗'}")
print()

# Test 2: Check instance directory
print("Test 2: Instance Directory")
instance_path = os.path.join(script_dir, 'instance')
print(f"  Path: {instance_path}")
print(f"  Exists: {os.path.exists(instance_path)}")

if os.path.exists(instance_path):
    print(f"  Writable: {os.access(instance_path, os.W_OK)}")
    print(f"  Readable: {os.access(instance_path, os.R_OK)}")
else:
    parent = os.path.dirname(instance_path)
    print(f"  Parent writable: {os.access(parent, os.W_OK)}")
    
    # Try to create it
    try:
        os.makedirs(instance_path, exist_ok=True)
        print("  Creation: ✓ Successfully created")
    except (OSError, PermissionError) as e:
        print(f"  Creation: ✗ Failed - {e}")
print()

# Test 3: Check alternative temp location
print("Test 3: Alternative Temp Location")
temp_instance = os.path.join(tempfile.gettempdir(), 'obsidian_scout_instance')
print(f"  Path: {temp_instance}")
try:
    os.makedirs(temp_instance, exist_ok=True)
    print("  Creation: ✓ Successfully created")
    print(f"  Writable: {os.access(temp_instance, os.W_OK)}")
    
    # Try to create a test file
    test_file = os.path.join(temp_instance, 'test.txt')
    with open(test_file, 'w') as f:
        f.write('test')
    print("  File write: ✓ Success")
    os.remove(test_file)
except Exception as e:
    print(f"  Error: ✗ {e}")
print()

# Test 4: Check virtual environment
print("Test 4: Virtual Environment")
venv_path = os.path.join(script_dir, '.venv')
print(f"  Path: {venv_path}")
print(f"  Exists: {os.path.exists(venv_path)}")

if os.path.exists(venv_path):
    venv_python = os.path.join(venv_path, 'Scripts', 'python.exe')
    print(f"  Python: {os.path.exists(venv_python)}")
    
    # Check if we're running in the venv
    running_in_venv = sys.executable.startswith(venv_path)
    print(f"  Active: {'✓' if running_in_venv else '✗ (Not using venv!)'}")
print()

# Test 5: Check required files
print("Test 5: Required Files")
required_files = ['run.py', 'requirements.txt', 'app_config.json', 'START.bat']
for filename in required_files:
    filepath = os.path.join(script_dir, filename)
    exists = os.path.exists(filepath)
    print(f"  {filename}: {'✓' if exists else '✗'}")
print()

# Summary
print("=" * 60)
print("Summary")
print("=" * 60)

can_use_project_instance = False
if os.path.exists(instance_path):
    can_use_project_instance = os.access(instance_path, os.W_OK)
else:
    parent = os.path.dirname(instance_path)
    can_use_project_instance = os.access(parent, os.W_OK)

if can_use_project_instance:
    print("✓ Project instance directory is accessible")
    print("  The app should run normally in the project directory")
else:
    print("✗ Project instance directory is NOT accessible")
    print("  The app will use fallback location:")
    print(f"  {temp_instance}")

print()
print("Recommendations:")
if not can_use_project_instance:
    print("  1. Try moving project out of OneDrive")
    print("  2. Check folder permissions (right-click → Properties → Security)")
    print("  3. Run START.bat instead of double-clicking run.py")
    print("  4. Or use command line: cd to project dir then 'python run.py'")
else:
    print("  ✓ Everything looks good!")
    print("  You can run the app with: START.bat or 'python run.py'")

print()
print("To test the actual app, run: python run.py")
print("=" * 60)
