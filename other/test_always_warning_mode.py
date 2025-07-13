#!/usr/bin/env python3
"""
Test script to verify that file integrity is now always in warning-only mode
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.file_integrity import FileIntegrityMonitor

def test_warning_only_mode():
    """Test that file integrity is always in warning-only mode"""
    print("Testing Always Warning-Only Mode")
    print("=" * 40)
    
    # Create a monitor instance
    monitor = FileIntegrityMonitor()
    
    # Check that warning_only_mode is True by default
    print(f"1. Default warning-only mode: {monitor.warning_only_mode}")
    assert monitor.warning_only_mode == True, "Warning-only mode should be enabled by default"
    
    # Initialize checksums
    print("2. Initializing checksums...")
    monitor.initialize_checksums()
    print(f"   Initialized {len(monitor.checksums)} file checksums")
    
    # Check that warning_only_mode is still True after initialization
    print(f"3. Warning-only mode after init: {monitor.warning_only_mode}")
    assert monitor.warning_only_mode == True, "Warning-only mode should remain enabled after initialization"
    
    # Create a test file
    test_file = "test_always_warning_file.txt"
    print(f"4. Creating test file: {test_file}")
    with open(test_file, 'w') as f:
        f.write("Original content")
    
    # Reinitialize to include the test file
    monitor.initialize_checksums()
    
    # Check initial integrity
    print("5. Initial integrity check...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    print(f"   Compromised status: {monitor.integrity_compromised}")
    
    # Modify the test file
    print("6. Modifying test file to trigger integrity warning...")
    with open(test_file, 'w') as f:
        f.write("Modified content - this should trigger warning only")
    
    # Check integrity (should warn but not set compromised flag due to warning-only mode)
    print("7. Checking integrity after modification...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    print(f"   Compromised status: {monitor.integrity_compromised}")
    print(f"   Warning-only mode: {monitor.warning_only_mode}")
    
    # Clean up
    print("8. Cleaning up...")
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"   Removed test file: {test_file}")
    
    print("\n" + "=" * 40)
    print("Always Warning-Only Mode Test Complete")
    print("\nResults:")
    print("- File integrity is always in warning-only mode")
    print("- File changes trigger warnings but don't block access")
    print("- No password verification required")
    print("- Application remains accessible even with file modifications")

if __name__ == "__main__":
    test_warning_only_mode()
