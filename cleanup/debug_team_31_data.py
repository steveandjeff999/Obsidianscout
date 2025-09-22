#!/usr/bin/env python3
"""
Debug script to check Team 31 scouting data and why it's not showing up
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import ScoutingData, Team, User, db
from app.utils.team_isolation import filter_scouting_data_by_scouting_team, get_current_scouting_team_number
from flask_login import current_user
import json

app = create_app()

with app.app_context():
    print("=== DEBUG: Team 31 Scouting Data Analysis ===\n")
    
    # Find Team 31
    team_31 = Team.query.filter_by(team_number=31).first()
    if not team_31:
        print("❌ Team 31 not found in database")
        exit(1)
    
    print(f"✅ Found Team 31: {team_31.team_name}")
    print(f"   Team ID: {team_31.id}")
    print(f"   Team scouting_team_number: {team_31.scouting_team_number}")
    print()
    
    # Check all scouting data for Team 31 (no filtering)
    all_data = ScoutingData.query.filter_by(team_id=team_31.id).all()
    print(f"📊 Total ScoutingData entries for Team 31: {len(all_data)}")
    
    if len(all_data) == 0:
        print("❌ No scouting data entries found for Team 31")
        exit(1)
    
    # Show breakdown by scouting team
    team_breakdown = {}
    for entry in all_data:
        team_num = entry.scouting_team_number
        if team_num not in team_breakdown:
            team_breakdown[team_num] = []
        team_breakdown[team_num].append(entry)
    
    print("\n📈 Scouting data breakdown by scouting team:")
    for scouting_team, entries in team_breakdown.items():
        print(f"   Scouting Team {scouting_team}: {len(entries)} entries")
        for i, entry in enumerate(entries[:3]):  # Show first 3 entries
            try:
                total_points = entry.calculate_metric('tot')
                print(f"      Entry {i+1}: ID={entry.id}, total_points={total_points}, scout={entry.scout_name}")
                if i == 0:  # Show data_json for first entry
                    print(f"                 data_json preview: {entry.data_json[:100]}...")
            except Exception as e:
                print(f"      Entry {i+1}: ID={entry.id}, ERROR calculating metric: {e}")
    
    print()
    
    # Find user with scouting team 5454
    user_5454 = User.query.filter_by(scouting_team_number=5454).first()
    if not user_5454:
        print("❌ No user found with scouting_team_number=5454")
        print("Available users:")
        users = User.query.all()
        for user in users[:10]:  # Show first 10
            print(f"   {user.username}: scouting_team_number={user.scouting_team_number}")
        exit(1)
    
    print(f"✅ Found user with scouting team 5454: {user_5454.username}")
    print()
    
    # Simulate being logged in as that user and test the filter
    print("🔍 Testing filter_scouting_data_by_scouting_team with scouting team 5454...")
    
    # Manually check what the filter should return
    from sqlalchemy import or_
    
    # This mimics what the filter should do for scouting_team_number=5454
    expected_query = ScoutingData.query.filter(
        ScoutingData.team_id == team_31.id
    ).filter(
        or_(ScoutingData.scouting_team_number == 5454,
            ScoutingData.scouting_team_number.is_(None))
    )
    
    expected_results = expected_query.all()
    print(f"   Expected results (team_id={team_31.id} AND (scouting_team=5454 OR scouting_team IS NULL)): {len(expected_results)} entries")
    
    for i, entry in enumerate(expected_results):
        try:
            total_points = entry.calculate_metric('tot')
            print(f"      Entry {i+1}: ID={entry.id}, scouting_team={entry.scouting_team_number}, total={total_points}")
        except Exception as e:
            print(f"      Entry {i+1}: ID={entry.id}, ERROR: {e}")
    
    print()
    
    # Test the actual filter function by temporarily setting a mock user
    class MockUser:
        def __init__(self):
            self.scouting_team_number = 5454
            self.is_authenticated = True
    
    # Test the filter
    with app.test_request_context():
        # Import flask_login and set current user
        from flask_login import login_user
        
        # Create a mock user context
        print("🧪 Testing filter_scouting_data_by_scouting_team function...")
        
        # Directly call the function and see what it returns
        from app.utils.team_isolation import get_current_scouting_team_number
        
        # Mock the current user for testing
        import app.utils.team_isolation as isolation_module
        original_get_team = isolation_module.get_current_scouting_team_number
        isolation_module.get_current_scouting_team_number = lambda: 5454
        
        try:
            filtered_query = filter_scouting_data_by_scouting_team().filter(ScoutingData.team_id == team_31.id)
            filtered_results = filtered_query.all()
            print(f"   filter_scouting_data_by_scouting_team results: {len(filtered_results)} entries")
            
            total_points_list = []
            for i, entry in enumerate(filtered_results):
                try:
                    total_points = entry.calculate_metric('tot')
                    total_points_list.append(total_points)
                    print(f"      Entry {i+1}: ID={entry.id}, scouting_team={entry.scouting_team_number}, total={total_points}")
                except Exception as e:
                    print(f"      Entry {i+1}: ID={entry.id}, ERROR: {e}")
            
            # Calculate average like the ranks route does
            if total_points_list:
                # Filter out zero points as the ranks route does
                scored_points = [p for p in total_points_list if p is not None and p != 0]
                if scored_points:
                    avg_points = sum(scored_points) / len(scored_points)
                    print(f"\n💯 Calculated average (excluding zeros): {avg_points}")
                    print(f"   Non-zero entries: {len(scored_points)}")
                    print(f"   Total entries: {len(total_points_list)}")
                else:
                    print(f"\n⚠️  All entries have 0 points")
                    print(f"   Raw total points: {total_points_list}")
            else:
                print(f"\n❌ No entries found by filter")
                
        finally:
            # Restore original function
            isolation_module.get_current_scouting_team_number = original_get_team
    
    print("\n" + "="*60)
    print("SUMMARY:")
    if len(all_data) > 0:
        scouting_team_5454_count = len([e for e in all_data if e.scouting_team_number == 5454])
        null_team_count = len([e for e in all_data if e.scouting_team_number is None])
        
        print(f"✅ Team 31 has {len(all_data)} total scouting entries")
        print(f"   - {scouting_team_5454_count} entries with scouting_team_number=5454")
        print(f"   - {null_team_count} entries with scouting_team_number=NULL")
        
        if scouting_team_5454_count > 0 or null_team_count > 0:
            print("✅ Expected to see data when logged in as scouting team 5454")
        else:
            print("❌ No data visible to scouting team 5454")
            print("   Check if entries have a different scouting_team_number")
    
    print("="*60)
