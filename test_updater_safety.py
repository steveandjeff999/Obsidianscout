#!/usr/bin/env python3
"""
Test script to verify the remote updater won't kill itself
"""
import os
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent / 'app'))

from utils.remote_updater import stop_server_on_port, kill_server_processes

def test_self_protection():
    """Test that the updater won't kill itself"""
    current_pid = os.getpid()
    print(f"Current process PID: {current_pid}")
    
    # Test stop_server_on_port
    print("Testing stop_server_on_port with current PID protected...")
    try:
        killed = stop_server_on_port(8080, [current_pid])
        print(f"stop_server_on_port returned: {killed}")
        if current_pid in killed:
            print("ERROR: Function would kill itself!")
        else:
            print("SUCCESS: Function properly protects itself")
    except Exception as e:
        print(f"Exception in stop_server_on_port: {e}")
    
    # Test kill_server_processes
    print("\nTesting kill_server_processes with current PID protected...")
    try:
        killed = kill_server_processes([current_pid])
        print(f"kill_server_processes returned: {killed}")
        if current_pid in killed:
            print("ERROR: Function would kill itself!")
        else:
            print("SUCCESS: Function properly protects itself")
    except Exception as e:
        print(f"Exception in kill_server_processes: {e}")

if __name__ == "__main__":
    test_self_protection()
