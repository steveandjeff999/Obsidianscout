#!/usr/bin/env python3
"""
Startup script that forces the use of Waitress as the WSGI server.
This script sets the FORCE_WAITRESS environment variable and starts the application.
"""

import os
import sys

# Force Waitress usage
os.environ['FORCE_WAITRESS'] = '1'

# Import and run the main application
if __name__ == '__main__':
    print("🚀 Starting FRC Scouting Platform with Waitress WSGI Server")
    print("=" * 60)
    
    # Import the main run module
    import run
