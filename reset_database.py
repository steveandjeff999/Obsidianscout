#!/usr/bin/env python3
"""
Database reset script for the FRC Scouting Platform.
This script will delete the existing database and recreate it with default data.
Use with caution - this will delete all existing data!
"""

import os
import sys
from app import create_app, db
from app.utils.database_init import initialize_database

def reset_database():
    """Reset the database by deleting and recreating it"""
    print("=" * 60)
    print("DATABASE RESET SCRIPT")
    print("=" * 60)
    print("WARNING: This will delete ALL existing data!")
    print("This includes:")
    print("- All users and roles")
    print("- All teams and events")
    print("- All matches and scouting data")
    print("- All configuration settings")
    print("=" * 60)
    
    # Get confirmation
    confirm = input("Are you sure you want to reset the database? (type 'YES' to confirm): ")
    if confirm != 'YES':
        print("Database reset cancelled.")
        return
    
    # Additional confirmation
    confirm2 = input("This action cannot be undone. Type 'DELETE ALL DATA' to proceed: ")
    if confirm2 != 'DELETE ALL DATA':
        print("Database reset cancelled.")
        return
    
    print("Proceeding with database reset...")
    
    # Delete the database file
    db_path = os.path.join('instance', 'scouting.db')
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Deleted database file: {db_path}")
    else:
        print("Database file not found, creating new database...")
    
    # Recreate the database with default data
    print("Creating new database with default data...")
    initialize_database()
    
    print("=" * 60)
    print("Database reset complete!")
    print("Default admin user created:")
    print("  Username: admin")
    print("  Password: password")
    print("=" * 60)
    print("IMPORTANT: Change the admin password after first login!")
    print("=" * 60)

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        reset_database()
