#!/usr/bin/env python3
"""
Database migration script to fix empty email fields in users table
"""

from app import create_app, db
from app.models import User
import time

def fix_empty_emails():
    """Convert empty email strings to NULL in database"""
    print("Fixing empty email fields in User table...")
    
    # Find users with empty email strings
    users_with_empty_emails = User.query.filter(User.email == '').all()
    count = len(users_with_empty_emails)
    
    if count > 0:
        print(f"Found {count} users with empty email fields. Converting to NULL...")
        
        # Update each user's email to None
        for user in users_with_empty_emails:
            print(f"  - Updating user: {user.username}")
            user.email = None
        
        # Commit changes
        db.session.commit()
        print(f"Successfully updated {count} users.")
    else:
        print("No users with empty email fields found.")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        # Fix empty email fields
        fix_empty_emails()
        
        # Output current users
        print("\nCurrent users in database:")
        for user in User.query.all():
            email_status = user.email if user.email else "None"
            print(f"  - {user.username} (Email: {email_status})")
            
        print("\nDatabase migration completed successfully!")
