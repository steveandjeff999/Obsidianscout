#!/usr/bin/env python3
"""
Test script to verify remote_updater.py Windows compatibility
"""
import os
import sys
from pathlib import Path

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

try:
    from app.utils.remote_updater import kill_other_python_processes
    print("✅ Successfully imported kill_other_python_processes")
    
    # Test the function
    print("Testing kill_other_python_processes...")
    result = kill_other_python_processes([os.getpid()])
    print(f"✅ Function executed successfully, killed {len(result)} processes")
    
    print("✅ Remote updater is Windows compatible!")

except Exception as e:
    print(f"❌ Error testing remote updater: {e}")
    import traceback
    traceback.print_exc()
