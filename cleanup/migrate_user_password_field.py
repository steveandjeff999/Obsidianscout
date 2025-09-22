#!/usr/bin/env python3
"""
Database Migration: Add must_change_password field to User model

This script adds the must_change_password field to the User table.
"""

import os
import sys

# Add the root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    print("Adding must_change_password field to User table...")
    
    try:
        # Check if column already exists
        result = db.session.execute(text("PRAGMA table_info(user)")).fetchall()
        columns = [row[1] for row in result]
        
        if 'must_change_password' in columns:
            print("✅ must_change_password field already exists in User table.")
        else:
            # Add the column
            db.session.execute(text("ALTER TABLE user ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
            db.session.commit()
            print("✅ Successfully added must_change_password field to User table.")
        
        print("✅ Database migration completed!")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.session.rollback()
        sys.exit(1)
