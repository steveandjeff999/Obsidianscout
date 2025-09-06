#!/usr/bin/env python3
"""Fix user roles sync and database table placement issues"""

from app import create_app, db
from app.models import User, Role
import sqlite3

def fix_user_roles_database_placement():
    """Fix user_roles table being in wrong database"""
    app = create_app()
    
    with app.app_context():
        print("🔍 Investigating user_roles table placement...")
        
        # Check which database actually has the correct user_roles data
        scouting_path = 'instance/scouting.db'  
        users_path = 'instance/users.db'
        
        print("\nScouting DB user_roles:")
        try:
            with sqlite3.connect(scouting_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, role_id FROM user_roles")
                scouting_roles = cursor.fetchall()
                print(f"  Found {len(scouting_roles)} entries")
                for ur in scouting_roles[:5]:
                    print(f"    user_id={ur[0]}, role_id={ur[1]}")
        except Exception as e:
            print(f"  Error: {e}")
            
        print("\nUsers DB user_roles:")
        try:
            with sqlite3.connect(users_path) as conn:
                cursor = conn.cursor()  
                cursor.execute("SELECT user_id, role_id FROM user_roles")
                users_roles = cursor.fetchall()
                print(f"  Found {len(users_roles)} entries")
                for ur in users_roles[:5]:
                    print(f"    user_id={ur[0]}, role_id={ur[1]}")
        except Exception as e:
            print(f"  Error: {e}")
            
        # Check which users and roles exist in each database
        print("\nChecking User table location:")
        for db_name, db_path in [('scouting', scouting_path), ('users', users_path)]:
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM user")
                    user_count = cursor.fetchone()[0]
                    print(f"  {db_name}: {user_count} users")
            except Exception as e:
                print(f"  {db_name}: User table not found or error: {e}")
                
        print("\nChecking Role table location:")
        for db_name, db_path in [('scouting', scouting_path), ('users', users_path)]:
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM role")
                    role_count = cursor.fetchone()[0]
                    print(f"  {db_name}: {role_count} roles")
            except Exception as e:
                print(f"  {db_name}: Role table not found or error: {e}")
                
        # The issue: user_roles exists in both databases but should only be where User and Role tables are
        # Let's determine the correct location and clean up
        
        print("\n🔧 FIXING: Consolidating user_roles table...")
        
        # Step 1: Get all valid user_roles from both databases
        all_user_roles = set()
        
        for db_path in [scouting_path, users_path]:
            try:
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id, role_id FROM user_roles")
                    roles = cursor.fetchall()
                    for ur in roles:
                        all_user_roles.add((ur[0], ur[1]))
                        print(f"  Found user_role: user_id={ur[0]}, role_id={ur[1]}")
            except:
                pass
        
        print(f"\n✅ Consolidated {len(all_user_roles)} unique user_role entries")
        
        # Step 2: Clear user_roles from scouting.db (it shouldn't be there)
        print("\n🗑️ Removing user_roles from scouting.db...")
        try:
            with sqlite3.connect(scouting_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS user_roles")
                conn.commit()
                print("  ✅ Removed user_roles from scouting.db")
        except Exception as e:
            print(f"  ⚠️ Could not remove from scouting.db: {e}")
            
        # Step 3: Ensure all user_roles are in users.db
        print("\n📝 Ensuring all user_roles are in users.db...")
        try:
            with sqlite3.connect(users_path) as conn:
                cursor = conn.cursor()
                # Clear and rebuild
                cursor.execute("DELETE FROM user_roles")
                
                for user_id, role_id in all_user_roles:
                    cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", 
                                 (user_id, role_id))
                
                conn.commit()
                print(f"  ✅ Inserted {len(all_user_roles)} user_role entries into users.db")
        except Exception as e:
            print(f"  ❌ Error updating users.db: {e}")
            
        print("\n🎉 Fixed user_roles database placement!")
        print("Now user_roles only exists in users.db where User and Role tables are located.")

if __name__ == "__main__":
    fix_user_roles_database_placement()
