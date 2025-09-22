#!/usr/bin/env python3
"""
Test script to verify port detection works
"""
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent / 'app'))

from utils.remote_updater import detect_original_server_port

def test_port_detection():
    """Test port detection functionality"""
    print("Testing port detection...")
    
    detected_port = detect_original_server_port()
    if detected_port:
        print(f"Detected server port: {detected_port}")
    else:
        print("No server port detected")
    
    return detected_port

if __name__ == "__main__":
    test_port_detection()
