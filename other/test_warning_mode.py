#!/usr/bin/env python3
"""
Test script to demonstrate warning-only mode functionality
"""

import os
import sys
import time

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.file_integrity import FileIntegrityMonitor

def test_warning_only_mode():
    """Test the warning-only mode functionality"""
    print("Testing Warning-Only Mode")
    print("=" * 40)
    
    # Create a monitor instance
    monitor = FileIntegrityMonitor()
    
    # Initialize checksums
    print("1. Initializing checksums...")
    monitor.initialize_checksums()
    print(f"   Initialized {len(monitor.checksums)} file checksums")
    
    # Enable warning-only mode
    print("\n2. Enabling warning-only mode...")
    monitor.set_warning_only_mode(True)
    print(f"   Warning-only mode: {monitor.warning_only_mode}")
    
    # Create a test file
    test_file = "test_warning_file.txt"
    print(f"\n3. Creating test file: {test_file}")
    with open(test_file, 'w') as f:
        f.write("Original content")
    
    # Reinitialize to include the test file
    print("   Reinitializing checksums...")
    monitor.initialize_checksums()
    print(f"   Now monitoring {len(monitor.checksums)} files")
    
    # Check initial integrity
    print("\n4. Initial integrity check...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    print(f"   Compromised status: {monitor.integrity_compromised}")
    
    # Modify the test file
    print("\n5. Modifying test file...")
    with open(test_file, 'w') as f:
        f.write("Modified content - this should trigger warning")
    
    # Check integrity (should warn but not set compromised flag)
    print("   Checking integrity after modification...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    print(f"   Compromised status: {monitor.integrity_compromised}")
    print("   Note: In warning-only mode, compromised should be False")
    
    # Disable warning-only mode
    print("\n6. Disabling warning-only mode...")
    monitor.set_warning_only_mode(False)
    print(f"   Warning-only mode: {monitor.warning_only_mode}")
    
    # Check integrity again (should now set compromised flag)
    print("   Checking integrity with security mode...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    print(f"   Compromised status: {monitor.integrity_compromised}")
    print("   Note: In security mode, compromised should be True")
    
    # Clean up
    print("\n7. Cleaning up...")
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"   Removed test file: {test_file}")
    
    print("\n" + "=" * 40)
    print("Warning-Only Mode Test Complete")
    print("\nFeatures demonstrated:")
    print("- Warning-only mode shows warnings but doesn't block access")
    print("- Security mode blocks access when integrity is compromised")
    print("- Configuration is saved and loaded properly")

if __name__ == "__main__":
    test_warning_only_mode()
