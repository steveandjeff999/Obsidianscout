#!/usr/bin/env python3
"""
Database migration script to add SharedGraph table for graph sharing functionality
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from app import create_app, db
from app.models import SharedGraph

def create_shared_graph_table():
    """Create the SharedGraph table"""
    app = create_app()
    
    with app.app_context():
        try:
            # Create the table
            db.create_all()
            print("✅ SharedGraph table created successfully!")
            
            # Verify the table was created
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'shared_graph' in tables:
                print("✅ Verified: shared_graph table exists in database")
                
                # Show table structure
                columns = inspector.get_columns('shared_graph')
                print("\nTable structure:")
                for column in columns:
                    print(f"  - {column['name']}: {column['type']}")
            else:
                print("❌ Error: shared_graph table was not created")
                return False
                
        except Exception as e:
            print(f"❌ Error creating SharedGraph table: {str(e)}")
            return False
    
    return True

if __name__ == "__main__":
    print("Creating SharedGraph table for graph sharing functionality...")
    success = create_shared_graph_table()
    
    if success:
        print("\n🎉 Migration completed successfully!")
        print("You can now use the graph sharing features.")
    else:
        print("\n💥 Migration failed!")
        sys.exit(1)
