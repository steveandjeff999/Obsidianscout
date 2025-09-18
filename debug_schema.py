#!/usr/bin/env python3
"""
Check ScoutingData schema and fix the fallback
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import ScoutingData, Team, db

app = create_app()

with app.app_context():
    print("=== ScoutingData Schema ===\n")
    
    entry = ScoutingData.query.first()
    if entry:
        print("ScoutingData attributes:")
        for attr in dir(entry):
            if not attr.startswith('_') and not callable(getattr(entry, attr)):
                value = getattr(entry, attr)
                print(f"  {attr}: {value}")
        
        print(f"\nHas scouting_team_number: {hasattr(entry, 'scouting_team_number')}")
        if hasattr(entry, 'scouting_team_number'):
            print(f"scouting_team_number value: {entry.scouting_team_number}")