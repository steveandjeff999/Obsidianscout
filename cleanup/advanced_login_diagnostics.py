#!/usr/bin/env python3
"""
Advanced Login Diagnostics
Deep investigation into login issues beyond just failed attempt accumulation
"""
import os
import sys
from datetime import datetime, timezone, timedelta

def comprehensive_login_diagnosis():
    """Comprehensive diagnosis of login issues"""
    try:
        from app import create_app
        from app.models import User, LoginAttempt, Role, db
        from werkzeug.security import check_password_hash
        
        app = create_app()
        
        with app.app_context():
            print("🔍 COMPREHENSIVE LOGIN DIAGNOSIS")
            print("=" * 60)
            
            # 1. Check superadmin account status
            print("1. SUPERADMIN ACCOUNT STATUS")
            print("-" * 40)
            
            superadmin = User.query.filter_by(username='superadmin').first()
            if not superadmin:
                print("CRITICAL: Superadmin user does not exist!")
                return
            
            print(f"Username: {superadmin.username}")
            print(f"Team Number: {superadmin.scouting_team_number}")
            print(f"Is Active: {superadmin.is_active}")
            print(f"Must Change Password: {superadmin.must_change_password}")
            print(f"Created: {superadmin.created_at}")
            print(f"Updated: {superadmin.updated_at}")
            print(f"Last Login: {superadmin.last_login}")
            print(f"Roles: {[role.name for role in superadmin.roles]}")
            
            # 2. Test password verification with multiple candidates
            print(f"\n2. PASSWORD VERIFICATION TESTS")
            print("-" * 40)
            
            test_passwords = [
                'JSHkimber1911',  # Known correct password
                'password',       # Default password
                'Password',       # Capitalized
                'superadmin',     # Username as password
                'admin',          # Simple admin
                '',               # Empty password
            ]
            
            working_passwords = []
            for pwd in test_passwords:
                if superadmin.check_password(pwd):
                    working_passwords.append(pwd)
                    print(f"Password '{pwd}': WORKS")
                else:
                    print(f"Password '{pwd}': Invalid")
            
            if not working_passwords:
                print("🚨 CRITICAL: NO WORKING PASSWORDS FOUND!")
            else:
                print(f"Working passwords: {working_passwords}")
            
            # 3. Test the exact login query used in auth.py
            print(f"\n3. DATABASE QUERY SIMULATION")
            print("-" * 40)
            
            # Simulate the exact query from auth.py
            test_username = 'superadmin'
            test_team_number = 0
            
            print(f"Testing query: User.query.filter_by(username='{test_username}', scouting_team_number={test_team_number})")
            
            # Test various team number formats
            team_variations = [0, '0', None, '']
            for team_var in team_variations:
                try:
                    if team_var is None or team_var == '':
                        user_found = User.query.filter_by(username=test_username).first()
                        query_desc = f"username='{test_username}' (no team filter)"
                    else:
                        user_found = User.query.filter_by(username=test_username, scouting_team_number=team_var).first()
                        query_desc = f"username='{test_username}', scouting_team_number={team_var} ({type(team_var).__name__})"
                    
                    if user_found:
                        print(f"Query '{query_desc}': Found user {user_found.username}")
                    else:
                        print(f"Query '{query_desc}': No user found")
                        
                except Exception as e:
                    print(f"Query '{query_desc}': Error - {e}")
            
            # 4. Check for duplicate users
            print(f"\n4. DUPLICATE USER CHECK")
            print("-" * 40)
            
            all_superadmins = User.query.filter_by(username='superadmin').all()
            print(f"Total 'superadmin' users found: {len(all_superadmins)}")
            
            if len(all_superadmins) > 1:
                print("🚨 MULTIPLE SUPERADMIN USERS FOUND!")
                for i, user in enumerate(all_superadmins):
                    print(f"   User {i+1}: ID={user.id}, Team={user.scouting_team_number}, Active={user.is_active}")
            
            # Check for case-sensitive issues
            all_similar_usernames = User.query.filter(User.username.ilike('superadmin')).all()
            print(f"Case-insensitive 'superadmin' matches: {len(all_similar_usernames)}")
            
            for user in all_similar_usernames:
                if user.username != 'superadmin':
                    print(f"⚠️ Similar username found: '{user.username}' (Team {user.scouting_team_number})")
            
            # 5. Check failed login attempts specifically
            print(f"\n5. FAILED LOGIN ATTEMPT ANALYSIS")
            print("-" * 40)
            
            # Recent failed attempts for superadmin
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            recent_failed = LoginAttempt.query.filter(
                LoginAttempt.username == 'superadmin',
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= recent_cutoff
            ).order_by(LoginAttempt.attempt_time.desc()).limit(10).all()
            
            print(f"Failed attempts for 'superadmin' in last hour: {len(recent_failed)}")
            
            if recent_failed:
                for attempt in recent_failed:
                    print(f"   {attempt.attempt_time}: IP {attempt.ip_address}, Team {attempt.team_number}")
            
            # Check for blocks
            from app.utils.brute_force_protection import get_login_status
            
            # We can't call get_login_status without request context, so check database directly
            block_cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
            blocking_attempts = LoginAttempt.query.filter(
                LoginAttempt.username == 'superadmin',
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= block_cutoff
            ).count()
            
            print(f"Failed attempts for 'superadmin' in last 15 minutes: {blocking_attempts}")
            if blocking_attempts >= 10:
                print("🚨 SUPERADMIN IS CURRENTLY BLOCKED BY BRUTE FORCE PROTECTION!")
            else:
                print("✅ Superadmin is not blocked by brute force protection")
            
            # 6. Database integrity checks
            print(f"\n6. DATABASE INTEGRITY CHECKS")
            print("-" * 40)
            
            # Check if password hash is corrupted
            if superadmin.password_hash:
                print(f"✅ Password hash exists: {len(superadmin.password_hash)} characters")
                print(f"✅ Hash preview: {superadmin.password_hash[:50]}...")
                
                # Check if it's a valid scrypt hash format
                if superadmin.password_hash.startswith('scrypt:'):
                    print("✅ Password hash format: scrypt (correct)")
                elif superadmin.password_hash.startswith('pbkdf2:'):
                    print("⚠️ Password hash format: pbkdf2 (older format)")
                else:
                    print("❌ Password hash format: Unknown/Invalid")
            else:
                print("🚨 CRITICAL: No password hash found!")
            
            # Check roles
            if superadmin.roles:
                for role in superadmin.roles:
                    role_obj = Role.query.get(role.id)
                    if role_obj:
                        print(f"✅ Role: {role_obj.name} (ID: {role_obj.id})")
                    else:
                        print(f"❌ Role ID {role.id} not found in database")
            else:
                print("❌ No roles assigned to superadmin")
            
            # 7. Test actual login flow
            print(f"\n7. LOGIN FLOW SIMULATION")
            print("-" * 40)
            
            print("Simulating login with correct credentials...")
            
            # Step 1: User lookup
            login_user = User.query.filter_by(username='superadmin', scouting_team_number=0).first()
            if login_user:
                print("✅ Step 1: User found by login query")
                
                # Step 2: Password check
                if login_user.check_password('JSHkimber1911'):
                    print("✅ Step 2: Password verification passed")
                    
                    # Step 3: Active check
                    if login_user.is_active:
                        print("✅ Step 3: User account is active")
                        
                        # Step 4: Block check (simulated)
                        if blocking_attempts < 10:
                            print("✅ Step 4: Not blocked by brute force protection")
                            print("🎉 LOGIN SHOULD SUCCEED - investigating why it doesn't...")
                        else:
                            print("❌ Step 4: BLOCKED by brute force protection")
                    else:
                        print("❌ Step 3: User account is DEACTIVATED")
                else:
                    print("❌ Step 2: Password verification FAILED")
                    # Test with database password directly
                    raw_hash = login_user.password_hash
                    direct_check = check_password_hash(raw_hash, 'JSHkimber1911')
                    print(f"   Direct hash check result: {direct_check}")
            else:
                print("❌ Step 1: User NOT FOUND by login query")
                
                # Try alternative queries
                alt_user = User.query.filter_by(username='superadmin').first()
                if alt_user:
                    print(f"   Alternative query found user with team: {alt_user.scouting_team_number}")
            
            print(f"\n8. SUMMARY AND RECOMMENDATIONS")
            print("-" * 40)
            
            issues_found = []
            
            if not working_passwords:
                issues_found.append("No working passwords found - password may be corrupted")
            
            if len(all_superadmins) > 1:
                issues_found.append("Multiple superadmin users exist")
            
            if blocking_attempts >= 10:
                issues_found.append("User is blocked by brute force protection")
            
            if not superadmin.is_active:
                issues_found.append("User account is deactivated")
            
            if not superadmin.roles:
                issues_found.append("No roles assigned")
            
            if issues_found:
                print("🚨 ISSUES FOUND:")
                for i, issue in enumerate(issues_found, 1):
                    print(f"   {i}. {issue}")
            else:
                print("✅ No obvious issues found - login should work")
                print("   The problem may be in the request/session handling")
            
    except Exception as e:
        print(f"❌ Error during comprehensive diagnosis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    comprehensive_login_diagnosis()
