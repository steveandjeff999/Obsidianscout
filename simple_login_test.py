#!/usr/bin/env python3
"""
Simple Login Database Test
Focus on the database query and password verification without HTTP context
"""
import os
import sys
from datetime import datetime, timedelta

def test_database_login():
    """Test just the database parts of login without HTTP context"""
    try:
        from app import create_app
        from app.models import User, LoginAttempt, Role, db
        
        app = create_app()
        
        with app.app_context():
            print("🔍 DATABASE LOGIN TEST")
            print("=" * 60)
            
            # Test credentials
            username = 'superadmin'
            password = 'JSHkimber1911'
            team_number = 0
            
            print(f"Testing database login with:")
            print(f"  Username: {username}")
            print(f"  Password: {password}")
            print(f"  Team Number: {team_number}")
            print()
            
            # Step 1: User lookup (exact query from auth.py)
            print("STEP 1: Database user lookup...")
            print(f"  Executing: User.query.filter_by(username='{username}', scouting_team_number={team_number}).first()")
            
            user = User.query.filter_by(username=username, scouting_team_number=team_number).first()
            
            if user is None:
                print("❌ User lookup FAILED")
                
                # Debug alternative queries
                print("\nDebugging alternative queries:")
                
                # Try without team number
                user_no_team = User.query.filter_by(username=username).first()
                if user_no_team:
                    print(f"  Found user without team filter: Team {user_no_team.scouting_team_number} (type: {type(user_no_team.scouting_team_number)})")
                    print(f"  Team comparison: {team_number} == {user_no_team.scouting_team_number} = {team_number == user_no_team.scouting_team_number}")
                    print(f"  Type comparison: {type(team_number)} vs {type(user_no_team.scouting_team_number)}")
                
                # Try with string team number
                user_str_team = User.query.filter_by(username=username, scouting_team_number='0').first()
                if user_str_team:
                    print(f"  Found user with string '0': {user_str_team.username}")
                
                # Try with None team number
                user_none_team = User.query.filter_by(username=username, scouting_team_number=None).first()
                if user_none_team:
                    print(f"  Found user with None team: {user_none_team.username}")
                
                return
            else:
                print(f"✅ User found: {user.username}")
                print(f"  ID: {user.id}")
                print(f"  Team: {user.scouting_team_number} (type: {type(user.scouting_team_number)})")
                print(f"  Active: {user.is_active}")
                print()
            
            # Step 2: Password check
            print("STEP 2: Password verification...")
            password_valid = user.check_password(password)
            print(f"  user.check_password('{password}'): {password_valid}")
            
            if not password_valid:
                print("❌ Password verification FAILED")
                
                # Debug the password hash
                print("\nDebugging password hash:")
                print(f"  Hash: {user.password_hash[:60]}...")
                print(f"  Hash type: {type(user.password_hash)}")
                
                # Direct hash check
                from werkzeug.security import check_password_hash
                direct_check = check_password_hash(user.password_hash, password)
                print(f"  Direct check_password_hash result: {direct_check}")
                
                return
            else:
                print("✅ Password verification successful")
                print()
            
            # Step 3: Active check
            print("STEP 3: Account active check...")
            if not user.is_active:
                print("❌ Account is DEACTIVATED")
                return
            else:
                print("✅ Account is active")
                print()
            
            # Step 4: Check recent failed attempts (manual brute force check)
            print("STEP 4: Manual brute force check...")
            
            # Count recent failed attempts
            cutoff_time = datetime.utcnow() - timedelta(minutes=15)
            recent_failed = LoginAttempt.query.filter(
                LoginAttempt.username == username,
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff_time
            ).count()
            
            print(f"  Failed attempts in last 15 minutes: {recent_failed}")
            
            if recent_failed >= 10:
                print("❌ Too many recent failed attempts - would be blocked")
                return
            else:
                print("✅ Not blocked by failed attempts")
                print()
            
            print("🎉 ALL DATABASE CHECKS PASSED!")
            print("   The database-level login should work")
            print()
            
            # Test creating a login attempt record
            print("TESTING: Recording successful login attempt...")
            try:
                from app.utils.brute_force_protection import BruteForceProtection
                
                # Create instance manually
                bf_protection = BruteForceProtection()
                
                # Record attempt manually
                new_attempt = LoginAttempt(
                    username=username,
                    team_number=team_number,
                    ip_address='127.0.0.1',  # Test IP
                    success=True,
                    attempt_time=datetime.utcnow()
                )
                
                db.session.add(new_attempt)
                db.session.commit()
                
                print("✅ Successfully recorded login attempt")
                
            except Exception as e:
                print(f"❌ Failed to record login attempt: {e}")
            
            # Check what might be different after remote updates
            print("\nCHECKING FOR POST-UPDATE ISSUES:")
            print("-" * 40)
            
            # Check if there are any uncommitted database changes
            if db.session.dirty:
                print(f"⚠️  Dirty session objects: {len(db.session.dirty)}")
                for obj in db.session.dirty:
                    print(f"     {type(obj).__name__}: {obj}")
            else:
                print("✅ No dirty session objects")
            
            # Check if there are any pending changes
            if db.session.new:
                print(f"⚠️  New session objects: {len(db.session.new)}")
            else:
                print("✅ No new session objects")
            
            # Check database connection
            try:
                db.session.execute(db.text('SELECT 1')).fetchone()
                print("✅ Database connection is healthy")
            except Exception as e:
                print(f"❌ Database connection issue: {e}")
    
    except Exception as e:
        print(f"❌ Error during database login test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_database_login()
