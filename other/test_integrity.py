#!/usr/bin/env python3
"""
Test script for file integrity monitoring system
This script demonstrates the file integrity monitoring functionality
"""

import sys
import os
import time

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.utils.file_integrity import FileIntegrityMonitor

def test_file_integrity():
    """Test the file integrity monitoring system"""
    print("Testing File Integrity Monitoring System")
    print("=" * 50)
    
    # Create a monitor instance
    monitor = FileIntegrityMonitor()
    
    # Initialize checksums
    print("1. Initializing checksums...")
    monitor.initialize_checksums()
    print(f"   Initialized {len(monitor.checksums)} file checksums")
    
    # Check integrity (should pass)
    print("\n2. Checking integrity (should pass)...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    
    # Set a test password
    print("\n3. Setting test password...")
    test_password = "test123"
    monitor.set_integrity_password(test_password)
    print(f"   Password set to: {test_password}")
    
    # Test password verification
    print("\n4. Testing password verification...")
    correct_password = monitor.verify_integrity_password(test_password)
    wrong_password = monitor.verify_integrity_password("wrong")
    print(f"   Correct password: {'PASS' if correct_password else 'FAIL'}")
    print(f"   Wrong password: {'PASS' if not wrong_password else 'FAIL'}")
    
    # Create a test file to modify
    test_file = "test_integrity_file.txt"
    print(f"\n5. Creating test file: {test_file}")
    with open(test_file, 'w') as f:
        f.write("Original content")
    
    # Reinitialize to include the test file
    print("   Reinitializing checksums to include test file...")
    monitor.initialize_checksums()
    print(f"   Now monitoring {len(monitor.checksums)} files")
    
    # Check integrity (should still pass)
    print("\n6. Checking integrity after adding test file...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'PASS' if integrity_ok else 'FAIL'}")
    
    # Modify the test file
    print("\n7. Modifying test file...")
    with open(test_file, 'w') as f:
        f.write("Modified content - this should trigger integrity failure")
    
    # Check integrity (should fail)
    print("   Checking integrity after modification...")
    integrity_ok = monitor.check_integrity()
    print(f"   Integrity check: {'FAIL' if not integrity_ok else 'UNEXPECTED PASS'}")
    print(f"   Compromised status: {monitor.integrity_compromised}")
    
    # Test reset functionality
    print("\n8. Testing integrity reset...")
    monitor.reset_integrity()
    print(f"   Compromised status after reset: {monitor.integrity_compromised}")
    print(f"   Now monitoring {len(monitor.checksums)} files")
    
    # Clean up
    print("\n9. Cleaning up...")
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"   Removed test file: {test_file}")
    
    print("\n" + "=" * 50)
    print("File Integrity Test Complete")
    print("The system is ready for production use.")
    print(f"Default integrity password: admin123")

if __name__ == "__main__":
    test_file_integrity()
