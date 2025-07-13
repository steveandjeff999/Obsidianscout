#!/usr/bin/env python3
"""
Test script to verify VersionManager configuration
"""
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.utils.version_manager import VersionManager

def test_version_manager():
    print("Testing VersionManager...")
    
    vm = VersionManager()
    print(f"Config path: {vm.config_path}")
    print(f"Config file exists: {os.path.exists(vm.config_path)}")
    print(f"Current version: {vm.get_current_version()}")
    print(f"Repository URL: {vm.config.get('repository_url', 'Not set')}")
    
    # Test GitHub update checking
    print("\nChecking for updates...")
    has_update, message = vm.check_for_updates_github()
    print(f"Update available: {has_update}")
    print(f"Message: {message}")
    
    if vm.config.get('remote_version'):
        print(f"Remote version: {vm.config['remote_version']}")

if __name__ == "__main__":
    test_version_manager()
