#!/usr/bin/env python3
"""
Comprehensive debug script to find where Team 31 data is hiding
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import ScoutingData, Team, User, db
import json
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("=== COMPREHENSIVE DEBUG: Finding Team 31 Data ===\n")
    
    # Check database file location
    db_url = str(db.engine.url)
    print(f"🗄️  Database URL: {db_url}")
    
    # If it's SQLite, show the actual file path
    if 'sqlite' in db_url.lower():
        db_file = db_url.replace('sqlite:///', '').replace('sqlite:///', '')
        if os.path.exists(db_file):
            file_size = os.path.getsize(db_file)
            print(f"   File exists: {db_file} ({file_size:,} bytes)")
        else:
            print(f"   File NOT found: {db_file}")
    print()
    
    # Check all teams in database
    all_teams = Team.query.all()
    print(f"📋 Total teams in database: {len(all_teams)}")
    
    # Look for any team with number 31 (could be multiple)
    teams_31 = Team.query.filter_by(team_number=31).all()
    print(f"🔍 Teams with number 31: {len(teams_31)}")
    for team in teams_31:
        print(f"   Team ID {team.id}: {team.team_name} (scouting_team: {team.scouting_team_number})")
    print()
    
    # Check all scouting data entries
    all_scouting_data = ScoutingData.query.all()
    print(f"📊 Total ScoutingData entries: {len(all_scouting_data)}")
    
    if len(all_scouting_data) == 0:
        print("❌ No scouting data entries found at all!")
        print("\nLet's check if data might be in a different table or database...")
        
        # Try to check table structure
        try:
            result = db.engine.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
            tables = [row[0] for row in result]
            print(f"📋 Available tables: {tables}")
            
            # Check if scouting_data table exists and has data
            if 'scouting_data' in tables:
                result = db.engine.execute(text("SELECT COUNT(*) FROM scouting_data;"))
                count = result.fetchone()[0]
                print(f"   scouting_data table has {count} rows")
                
                if count > 0:
                    # Show first few rows
                    result = db.engine.execute(text("SELECT id, team_id, scouting_team_number, scout_name FROM scouting_data LIMIT 5;"))
                    print("   First 5 rows:")
                    for row in result:
                        print(f"      ID: {row[0]}, team_id: {row[1]}, scouting_team: {row[2]}, scout: {row[3]}")
        except Exception as e:
            print(f"   Error checking tables: {e}")
            
        exit(1)
    
    # Group scouting data by team
    team_data_count = {}
    scouting_team_breakdown = {}
    
    for entry in all_scouting_data:
        # Count by team_id
        if entry.team_id not in team_data_count:
            team_data_count[entry.team_id] = 0
        team_data_count[entry.team_id] += 1
        
        # Count by scouting_team_number
        st = entry.scouting_team_number
        if st not in scouting_team_breakdown:
            scouting_team_breakdown[st] = 0
        scouting_team_breakdown[st] += 1
    
    print("📈 Scouting data by team:")
    for team_id, count in sorted(team_data_count.items()):
        team = Team.query.get(team_id)
        team_name = f"{team.team_name} (#{team.team_number})" if team else f"Unknown team"
        print(f"   Team ID {team_id}: {count} entries - {team_name}")
    print()
    
    print("👥 Scouting data by scouting team:")
    for scouting_team, count in sorted(scouting_team_breakdown.items()):
        print(f"   Scouting Team {scouting_team}: {count} entries")
    print()
    
    # Look for any entries that might be for "Team 31" (check team numbers)
    entries_for_team_31 = []
    for entry in all_scouting_data:
        team = Team.query.get(entry.team_id)
        if team and team.team_number == 31:
            entries_for_team_31.append(entry)
    
    print(f"🎯 Scouting entries specifically for team number 31: {len(entries_for_team_31)}")
    for entry in entries_for_team_31:
        try:
            total = entry.calculate_metric('tot')
            print(f"   Entry ID {entry.id}: total={total}, scouting_team={entry.scouting_team_number}")
        except Exception as e:
            print(f"   Entry ID {entry.id}: ERROR calculating total: {e}")
    
    # Check if there are entries for scouting team 5454
    entries_from_5454 = [e for e in all_scouting_data if e.scouting_team_number == 5454]
    print(f"\n🏷️  Entries created by scouting team 5454: {len(entries_from_5454)}")
    for entry in entries_from_5454:
        team = Team.query.get(entry.team_id)
        team_info = f"Team {team.team_number} ({team.team_name})" if team else f"Team ID {entry.team_id}"
        try:
            total = entry.calculate_metric('tot')
            print(f"   {team_info}: total={total}")
        except Exception as e:
            print(f"   {team_info}: ERROR calculating total: {e}")
    
    print("\n" + "="*70)
    print("🔍 DIAGNOSIS:")
    
    if len(entries_for_team_31) == 0 and len(entries_from_5454) == 0:
        print("❌ No scouting data found for Team 31 OR created by scouting team 5454")
        print("   This suggests either:")
        print("   1. The data is in a different database file")
        print("   2. The data was created with different team numbers")
        print("   3. The graph is showing cached/old data")
    elif len(entries_from_5454) > 0 and len(entries_for_team_31) == 0:
        print("✅ Found data created by scouting team 5454, but not for team number 31")
        print("   The graph might be showing data for a different team")
    elif len(entries_for_team_31) > 0:
        print("✅ Found data for team number 31")
        scouting_teams = set(e.scouting_team_number for e in entries_for_team_31)
        print(f"   Created by scouting teams: {scouting_teams}")
    
    print("="*70)