#!/usr/bin/env python3
"""
Test Autonomous Sync System
Validates that all user operations (add/update/delete/hard_delete) 
automatically create DatabaseChange records for sync without manual intervention.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, DatabaseChange, Role
from datetime import datetime
import json

def test_autonomous_sync():
    """Test that all user operations create proper change records automatically"""
    app = create_app()
    
    with app.app_context():
        print("🔄 Testing Autonomous Sync System...")
        print("=" * 50)
        
        # Clear old test data
        test_users = User.query.filter(User.username.like('autotest_%')).all()
        for user in test_users:
            db.session.delete(user)
        db.session.commit()
        
        # Clear old test change records
        test_changes = DatabaseChange.query.filter(
            db.or_(
                DatabaseChange.change_data.like('%autotest_%'),
                DatabaseChange.old_data.like('%autotest_%')
            )
        ).all()
        for change in test_changes:
            db.session.delete(change)
        db.session.commit()
        
        initial_change_count = DatabaseChange.query.count()
        print(f"📊 Initial change count: {initial_change_count}")
        
        # Test 1: User Creation (INSERT)
        print("\n1️⃣ Testing User Creation...")
        admin_role = Role.query.filter_by(name='admin').first()
        if not admin_role:
            admin_role = Role(name='admin')
            db.session.add(admin_role)
            db.session.commit()
        
        test_user = User(
            username='autotest_user1',
            scouting_team_number=9999,
            is_active=True
        )
        test_user.set_password('test123')  # Use the method to set password
        test_user.roles.append(admin_role)
        db.session.add(test_user)
        db.session.commit()
        
        create_changes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.operation == 'insert'
        ).order_by(DatabaseChange.timestamp.desc()).limit(5).all()
        
        create_found = False
        for change in create_changes:
            if change.change_data and 'autotest_user1' in str(change.change_data):
                create_found = True
                print(f"✅ User creation tracked: ID={change.id}, timestamp={change.timestamp}")
                break
        
        if not create_found:
            print("❌ User creation NOT tracked automatically")
        
        # Test 2: User Update (UPDATE)
        print("\n2️⃣ Testing User Update...")
        test_user.scouting_team_number = 8888
        db.session.commit()
        
        update_changes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.operation == 'update'
        ).order_by(DatabaseChange.timestamp.desc()).limit(5).all()
        
        update_found = False
        for change in update_changes:
            if change.change_data and 'autotest_user1' in str(change.change_data):
                update_found = True
                print(f"✅ User update tracked: ID={change.id}, timestamp={change.timestamp}")
                break
        
        if not update_found:
            print("❌ User update NOT tracked automatically")
        
        # Test 3: Soft Delete (UPDATE - deactivation)
        print("\n3️⃣ Testing Soft Delete (deactivation)...")
        test_user.is_active = False
        db.session.commit()
        
        soft_delete_changes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.operation == 'update'
        ).order_by(DatabaseChange.timestamp.desc()).limit(3).all()
        
        soft_delete_found = False
        for change in soft_delete_changes:
            if (change.change_data and 'autotest_user1' in str(change.change_data) 
                and '"is_active": false' in str(change.change_data)):
                soft_delete_found = True
                print(f"✅ Soft delete tracked: ID={change.id}, timestamp={change.timestamp}")
                break
        
        if not soft_delete_found:
            print("❌ Soft delete NOT tracked automatically")
        
        # Test 4: Hard Delete (DELETE)
        print("\n4️⃣ Testing Hard Delete...")
        user_id = test_user.id
        username = test_user.username
        
        # This should trigger both manual tracking and automatic tracking
        db.session.delete(test_user)
        db.session.commit()
        
        delete_changes = DatabaseChange.query.filter(
            DatabaseChange.table_name == 'user',
            DatabaseChange.operation == 'delete'
        ).order_by(DatabaseChange.timestamp.desc()).limit(5).all()
        
        delete_found = False
        for change in delete_changes:
            if (change.old_data and 
                (f'"id": {user_id}' in str(change.old_data) or 
                 f'"username": "{username}"' in str(change.old_data))):
                delete_found = True
                print(f"✅ Hard delete tracked: ID={change.id}, timestamp={change.timestamp}")
                break
        
        if not delete_found:
            print("❌ Hard delete NOT tracked automatically")
        
        # Summary
        final_change_count = DatabaseChange.query.count()
        new_changes = final_change_count - initial_change_count
        
        print(f"\n📊 Summary:")
        print(f"   Initial changes: {initial_change_count}")
        print(f"   Final changes: {final_change_count}")
        print(f"   New changes created: {new_changes}")
        print(f"   Expected: 4 (insert, update, soft delete, hard delete)")
        
        # Check autonomous sync status
        all_tracked = create_found and update_found and soft_delete_found and delete_found
        
        if all_tracked:
            print("\n🎉 AUTONOMOUS SYNC FULLY FUNCTIONAL!")
            print("   All user operations automatically create change records")
            print("   No manual intervention required")
        else:
            print("\n⚠️  Autonomous sync has gaps:")
            if not create_found: print("   - User creation not tracked")
            if not update_found: print("   - User updates not tracked")  
            if not soft_delete_found: print("   - Soft deletes not tracked")
            if not delete_found: print("   - Hard deletes not tracked")
        
        # Show recent changes for verification
        print(f"\n📋 Recent DatabaseChange records:")
        recent_changes = DatabaseChange.query.order_by(
            DatabaseChange.timestamp.desc()
        ).limit(10).all()
        
        for i, change in enumerate(recent_changes, 1):
            data_preview = ""
            if change.change_data:
                try:
                    data = json.loads(change.change_data)
                    if 'username' in data:
                        data_preview = f" (user: {data['username']})"
                except:
                    pass
            elif change.old_data:
                try:
                    data = json.loads(change.old_data)
                    if 'username' in data:
                        data_preview = f" (user: {data['username']})"
                except:
                    pass
            
            print(f"   {i:2d}. {change.table_name}.{change.operation} "
                  f"at {change.timestamp.strftime('%H:%M:%S')}{data_preview}")
        
        return all_tracked

if __name__ == "__main__":
    success = test_autonomous_sync()
    if success:
        print(f"\n✅ Autonomous sync system is working perfectly!")
        sys.exit(0)
    else:
        print(f"\n❌ Autonomous sync system needs fixes")
        sys.exit(1)
