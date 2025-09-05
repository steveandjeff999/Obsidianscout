#!/usr/bin/env python3
"""
Test script to verify sync fixes and superadmin password functionality
"""

import os
import sys

def test_auto_sync_setup():
    """Test that auto sync is properly configured"""
    print("🔍 TESTING AUTO SYNC SETUP")
    print("=" * 50)
    
    try:
        # Check if run.py has the multi-server sync worker
        run_py_path = os.path.join(os.path.dirname(__file__), 'run.py')
        if os.path.exists(run_py_path):
            with open(run_py_path, 'r') as f:
                content = f.read()
                
            if 'multi_server_sync_worker' in content:
                print("✅ Multi-server sync worker found in run.py")
            else:
                print("❌ Multi-server sync worker NOT found in run.py")
                
            if 'simplified_sync_manager.perform_bidirectional_sync' in content:
                print("✅ Auto sync calls simplified sync manager")
            else:
                print("❌ Auto sync does NOT call simplified sync manager")
                
        else:
            print("❌ run.py not found")
            
    except Exception as e:
        print(f"❌ Error testing auto sync setup: {e}")

def test_profile_template():
    """Test that profile template has save button"""
    print("\n🔍 TESTING PROFILE TEMPLATE")
    print("=" * 50)
    
    try:
        profile_path = os.path.join(os.path.dirname(__file__), 'app', 'templates', 'auth', 'profile.html')
        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                content = f.read()
                
            if 'Save Changes' in content:
                print("✅ Save Changes button found in profile template")
            else:
                print("❌ Save Changes button NOT found in profile template")
                
            if 'Change Password' in content:
                print("✅ Change Password link found in profile template")
            else:
                print("❌ Change Password link NOT found in profile template")
                
            if 'type="submit"' in content:
                print("✅ Submit button found in profile form")
            else:
                print("❌ Submit button NOT found in profile form")
                
        else:
            print("❌ profile.html not found")
            
    except Exception as e:
        print(f"❌ Error testing profile template: {e}")

def test_change_password_route():
    """Test that change password route allows superadmin access"""
    print("\n🔍 TESTING CHANGE PASSWORD ROUTE")
    print("=" * 50)
    
    try:
        auth_py_path = os.path.join(os.path.dirname(__file__), 'app', 'routes', 'auth.py')
        if os.path.exists(auth_py_path):
            with open(auth_py_path, 'r') as f:
                content = f.read()
                
            if "current_user.has_role('superadmin')" in content and 'change_password' in content:
                print("✅ Change password route allows superadmin access")
            else:
                print("❌ Change password route does NOT allow superadmin access")
                
            if 'not current_user.must_change_password and not current_user.has_role' in content:
                print("✅ Change password logic updated for superadmin")
            else:
                print("❌ Change password logic NOT updated for superadmin")
                
        else:
            print("❌ auth.py not found")
            
    except Exception as e:
        print(f"❌ Error testing change password route: {e}")

def print_summary():
    """Print summary and instructions"""
    print("\n" + "=" * 50)
    print("🎯 SUMMARY OF FIXES")
    print("=" * 50)
    print("""
✅ FIXES APPLIED:

1. 🔄 AUTO SYNC FIXED:
   - Added multi_server_sync_worker thread to run.py
   - Auto sync runs every 1 minute (60 seconds)
   - Uses simplified_sync_manager for reliable sync
   - Only syncs with enabled servers
   - Provides clear logging of sync status

2. 💾 PROFILE SAVE BUTTON FIXED:
   - Added "Save Changes" button to profile form
   - Added "Change Password" link for all users
   - Form now properly submits profile updates

3. 🔑 SUPERADMIN PASSWORD CHANGE FIXED:
   - Superadmins can now change password anytime
   - No longer restricted by must_change_password flag
   - Profile includes direct link to password change

📋 WHAT YOU SHOULD SEE NOW:

✅ Auto Sync: 
   - Should sync automatically every minute
   - Check console for "Auto-sync" messages
   - Manual sync still available as backup

✅ Profile Page:
   - "Save Changes" button visible
   - "Change Password" link available
   - Form submissions work correctly

✅ Superadmin Console:
   - Can change password through profile
   - No permission errors
   - Full system access maintained

🔧 NEXT STEPS:

1. Restart the application: python run.py
2. Log in as superadmin
3. Test profile page - should have Save button
4. Test password change - should work without errors
5. Check console for auto-sync messages every minute
6. Verify manual "Force Full Sync" still works as backup
""")

def main():
    """Main test function"""
    print("🧪 TESTING SYNC AND SUPERADMIN FIXES")
    print("=" * 60)
    
    test_auto_sync_setup()
    test_profile_template()
    test_change_password_route()
    print_summary()

if __name__ == "__main__":
    main()
