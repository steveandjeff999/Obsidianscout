"""
Migration script to add ActivityLog table to the database
"""
import sys
import os
import sqlite3
from datetime import datetime

# Add the parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate():
    # Get the path to the database file
    db_path = os.path.join('instance', 'scouting.db')
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if the table already exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='activity_log'")
    if cursor.fetchone():
        print("The activity_log table already exists.")
        conn.close()
        return
    
    # Create the activity_log table
    cursor.execute('''
    CREATE TABLE activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        action_type TEXT,
        page TEXT,
        element_id TEXT,
        element_type TEXT,
        data TEXT,
        ip_address TEXT,
        user_agent TEXT,
        FOREIGN KEY (user_id) REFERENCES user(id)
    )
    ''')
    
    # Create an index on the timestamp for faster queries
    cursor.execute('CREATE INDEX idx_activity_log_timestamp ON activity_log(timestamp)')
    
    # Create an index on the user_id for faster queries
    cursor.execute('CREATE INDEX idx_activity_log_user_id ON activity_log(user_id)')
    
    # Create an index on the action_type for faster queries
    cursor.execute('CREATE INDEX idx_activity_log_action_type ON activity_log(action_type)')
    
    # Commit the changes
    conn.commit()
    
    # Insert an initial log entry
    cursor.execute('''
    INSERT INTO activity_log (user_id, username, timestamp, action_type, page, data)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (None, 'System', datetime.utcnow().isoformat(), 'system', '/system', 'Activity logging system initialized'))
    
    # Commit again
    conn.commit()
    conn.close()
    
    print("Successfully created activity_log table in the database.")
    print("Activity logging system has been initialized.")

if __name__ == "__main__":
    migrate()
