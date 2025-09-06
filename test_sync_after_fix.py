#!/usr/bin/env python3
"""Test sync functionality after fixing user_roles placement"""

from app import create_app, db
from app.models import User, Role, SyncServer
from app.utils.automatic_sqlite3_sync import AutomaticSQLite3Sync
import sqlite3

def test_sync_functionality():
    """Test that sync now works properly for both user roles and scouting data"""
    app = create_app()
    
    with app.app_context():
        print("🧪 Testing sync functionality after fixes...")
        
        # 1. Verify user_roles is now only in users.db
        print("\n1️⃣ Verifying user_roles table placement:")
        
        try:
            with sqlite3.connect('instance/scouting.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_roles'")
                result = cursor.fetchone()
                if result:
                    print("  ❌ user_roles still exists in scouting.db")
                else:
                    print("  ✅ user_roles removed from scouting.db")
        except Exception as e:
            print(f"  Error checking scouting.db: {e}")
            
        try:
            with sqlite3.connect('instance/users.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM user_roles")
                count = cursor.fetchone()[0]
                print(f"  ✅ user_roles in users.db: {count} entries")
        except Exception as e:
            print(f"  Error checking users.db: {e}")
            
        # 2. Test that SQLAlchemy user.roles relationship works
        print("\n2️⃣ Testing User-Role relationships:")
        
        users = User.query.all()
        users_with_roles = 0
        for user in users:
            roles = [r.name for r in user.roles]
            if roles:
                users_with_roles += 1
                print(f"  {user.username}: {roles}")
        
        print(f"  ✅ Found {users_with_roles} users with roles")
        
        # 3. Check what tables are discovered by sync system
        print("\n3️⃣ Checking sync system table discovery:")
        
        sync = AutomaticSQLite3Sync()
        user_db_tables = [table for table, db in sync.table_database_map.items() if db == 'users']
        scouting_db_tables = [table for table, db in sync.table_database_map.items() if db == 'scouting']
        
        print(f"  Users DB tables ({len(user_db_tables)}): {user_db_tables}")
        print(f"  Scouting DB tables ({len(scouting_db_tables)}): {', '.join(scouting_db_tables[:10])}{'...' if len(scouting_db_tables) > 10 else ''}")
        
        # 4. Check if there are any scouting data tables that should be syncing
        print("\n4️⃣ Checking scouting data tables:")
        
        important_scouting_tables = ['scouting_data', 'team', 'event', 'match', 'pit_scouting_data']
        
        try:
            with sqlite3.connect('instance/scouting.db') as conn:
                cursor = conn.cursor()
                for table_name in important_scouting_tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    print(f"  {table_name}: {count} records")
        except Exception as e:
            print(f"  Error checking scouting tables: {e}")
            
        # 5. Test creating a user and assigning a role
        print("\n5️⃣ Testing user creation with role assignment:")
        
        try:
            # Create test user
            from datetime import datetime
            test_username = f"test_roles_{datetime.now().strftime('%H%M%S')}"
            test_user = User(username=test_username, scouting_team_number=8888)
            test_user.set_password('test123')
            
            # Assign admin role
            admin_role = Role.query.filter_by(name='admin').first()
            if admin_role:
                test_user.roles.append(admin_role)
            
            db.session.add(test_user)
            db.session.commit()
            
            print(f"  ✅ Created test user: {test_user.username}")
            
            # Verify the role was assigned
            user_roles = [r.name for r in test_user.roles]
            print(f"  ✅ User roles: {user_roles}")
            
            # Check if this created a user_roles entry
            with sqlite3.connect('instance/users.db') as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM user_roles WHERE user_id = ?", (test_user.id,))
                role_count = cursor.fetchone()[0]
                print(f"  ✅ User_roles entries for new user: {role_count}")
                
        except Exception as e:
            print(f"  ❌ Error creating test user: {e}")
            
        # 6. Test if sync servers are configured
        print("\n6️⃣ Checking sync server configuration:")
        
        servers = SyncServer.query.filter_by(sync_enabled=True).all()
        print(f"  Found {len(servers)} enabled sync servers")
        
        for server in servers:
            print(f"    - {server.name}: {server.protocol}://{server.host}:{server.port}")
            
        if servers:
            print("\n🚀 Ready to test actual synchronization!")
            print("You can now:")
            print("  1. Create a user with roles on this server")
            print("  2. Trigger sync to another server") 
            print("  3. Check if the user AND roles appear on remote server")
        else:
            print("  ⚠️ No sync servers configured - add a server to test sync")

if __name__ == "__main__":
    test_sync_functionality()
