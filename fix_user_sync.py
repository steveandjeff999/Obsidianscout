"""
Add updated_at field to User model and fix sync consistency
"""

import sqlite3
from datetime import datetime
import os

def upgrade_database():
    """Add updated_at field to users table"""
    db_path = os.path.join('instance', 'scouting.db')
    
    if not os.path.exists(db_path):
        print("❌ Database not found!")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if updated_at column already exists
        cursor.execute("PRAGMA table_info(user)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'updated_at' not in columns:
            print("➕ Adding updated_at column to user table...")
            # First add column without default
            cursor.execute("""
                ALTER TABLE user 
                ADD COLUMN updated_at DATETIME
            """)
            
            # Set updated_at to current timestamp for existing users
            current_time = datetime.now().isoformat()
            cursor.execute("""
                UPDATE user 
                SET updated_at = ? 
                WHERE updated_at IS NULL
            """, (current_time,))
            
            print("✅ Added updated_at column successfully")
        else:
            print("✅ updated_at column already exists")
        
        # Check database changes table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='database_changes'
        """)
        
        if not cursor.fetchone():
            print("❌ database_changes table not found - run setup_concurrent_db.py first")
            return False
        else:
            print("✅ database_changes table exists")
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"❌ Error upgrading database: {e}")
        return False

def test_user_changes():
    """Test user change tracking"""
    from app import create_app, db
    from app.models import User, DatabaseChange
    
    app = create_app()
    with app.app_context():
        print("\n=== TESTING USER CHANGE TRACKING ===")
        
        # Create a test user
        test_user = User(
            username=f"test_user_{int(datetime.now().timestamp())}",
            email="test@example.com",
            is_active=True
        )
        test_user.set_password("password123")
        
        db.session.add(test_user)
        db.session.commit()
        
        print(f"✅ Created test user: {test_user.username} (ID: {test_user.id})")
        
        # Test soft delete
        print("🗑️  Testing soft delete...")
        test_user.is_active = False
        db.session.commit()
        
        # Check if change was tracked
        recent_changes = DatabaseChange.query.filter_by(
            table_name='user',
            record_id=str(test_user.id)
        ).order_by(DatabaseChange.timestamp.desc()).limit(3).all()
        
        print(f"📊 Recent changes for user {test_user.id}:")
        for change in recent_changes:
            print(f"  - {change.timestamp}: {change.operation} ({change.sync_status})")
        
        # Clean up
        db.session.delete(test_user)
        db.session.commit()
        print(f"🧹 Cleaned up test user")

if __name__ == "__main__":
    print("🔧 Upgrading database for sync consistency...")
    
    if upgrade_database():
        print("\n🔄 Testing change tracking...")
        test_user_changes()
        print("\n✅ Database upgrade and sync fixes completed!")
    else:
        print("\n❌ Database upgrade failed!")
