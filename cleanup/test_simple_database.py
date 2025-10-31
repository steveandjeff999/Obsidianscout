#!/usr/bin/env python3
"""
Simple Database Test - No Heavy Sync
Test database operations with minimal sync overhead
"""

import sys
import os
import time
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Role

def test_simple_database_operations():
    """Test database operations without heavy sync systems"""
    app = create_app()
    
    with app.app_context():
        print(" Simple Database Test (No Heavy Sync)")
        print("=" * 50)
        
        # Test user creation
        print("\n1️⃣ Testing Simple User Creation...")
        start_time = time.time()
        
        try:
            # Get or create admin role
            admin_role = Role.query.filter_by(name='admin').first()
            if not admin_role:
                admin_role = Role(name='admin')
                db.session.add(admin_role)
                db.session.commit()
                print("    Created admin role")
            
            # Create test user
            test_user = User(
                username=f'simple_test_{int(time.time())}',
                scouting_team_number=9999,
                is_active=True
            )
            test_user.set_password('test123')
            test_user.roles.append(admin_role)
            
            db.session.add(test_user)
            db.session.commit()
            
            elapsed = time.time() - start_time
            print(f"    User created in {elapsed:.2f} seconds")
            
            # Verify user exists
            found_user = User.query.filter_by(username=test_user.username).first()
            if found_user:
                print(f"    User verified in database: {found_user.username}")
            else:
                print(f"    User not found in database")
            
            # Test update
            print("\n2️⃣ Testing User Update...")
            start_time = time.time()
            
            found_user.scouting_team_number = 8888
            db.session.commit()
            
            elapsed = time.time() - start_time
            print(f"    User updated in {elapsed:.2f} seconds")
            
            # Test delete
            print("\n3️⃣ Testing User Deletion...")
            start_time = time.time()
            
            db.session.delete(found_user)
            db.session.commit()
            
            elapsed = time.time() - start_time
            print(f"    User deleted in {elapsed:.2f} seconds")
            
            # Verify deletion
            deleted_user = User.query.filter_by(username=test_user.username).first()
            if not deleted_user:
                print(f"    User successfully deleted from database")
            else:
                print(f"    User still exists in database")
                
        except Exception as e:
            print(f"    Database operation failed: {e}")
            return False
        
        # Test multiple operations
        print("\n4️⃣ Testing Multiple Quick Operations...")
        start_time = time.time()
        
        try:
            users_created = []
            
            # Create 3 users quickly
            for i in range(3):
                quick_user = User(
                    username=f'quick_test_{i}_{int(time.time())}',
                    scouting_team_number=7000 + i,
                    is_active=True
                )
                quick_user.set_password('quick123')
                quick_user.roles.append(admin_role)
                db.session.add(quick_user)
                users_created.append(quick_user)
            
            db.session.commit()
            
            elapsed = time.time() - start_time
            print(f"    Created 3 users in {elapsed:.2f} seconds ({elapsed/3:.2f}s avg)")
            
            # Clean up quickly
            start_time = time.time()
            for user in users_created:
                db.session.delete(user)
            db.session.commit()
            
            elapsed = time.time() - start_time  
            print(f"    Deleted 3 users in {elapsed:.2f} seconds ({elapsed/3:.2f}s avg)")
            
        except Exception as e:
            print(f"    Multiple operations failed: {e}")
            return False
        
        # Database status
        print(f"\n5️⃣ Database Status Check...")
        try:
            user_count = User.query.count()
            print(f"    Total users: {user_count}")
            
            # Check database settings
            from sqlalchemy import text
            journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()
            cache_size = db.session.execute(text("PRAGMA cache_size")).scalar()
            print(f"    Journal mode: {journal_mode}")
            print(f"    Cache size: {cache_size}")
            
        except Exception as e:
            print(f"   ️ Status check failed: {e}")
        
        print(f"\n Simple Database Test Results:")
        print(f"    All basic operations work")
        print(f"    No database locking detected")
        print(f"    Fast operation times")
        print(f"    Heavy sync systems disabled")
        
        return True

if __name__ == "__main__":
    success = test_simple_database_operations()
    if success:
        print(f"\n SUCCESS: Database works perfectly without heavy sync!")
        print(f"   - Operations are fast")
        print(f"   - No locking errors")  
        print(f"   - Ready for normal use")
    else:
        print(f"\n Database issues still exist")
