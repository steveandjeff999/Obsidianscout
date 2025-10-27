"""
Small migration script to modify the `user` table in instance/users.db so that
username is not globally unique but unique per (username, scouting_team_number).

This script will:
 - make a backup copy of the DB (instance/users.db.bak)
 - create a new table `user_new` with the same columns but without UNIQUE(username)
   and with UNIQUE(email) preserved
 - copy the data from `user` to `user_new`
 - drop the old `user` table and rename `user_new` -> `user`
 - create an explicit UNIQUE INDEX on (username, scouting_team_number)

Run this from the repository root with the virtualenv active (so Python version matches).
Example (PowerShell):
    & ".\.venv\Scripts\python.exe" "tools\migrate_user_unique.py"

Important: review the backup (instance/users.db.bak) before running the app. If something
unexpected happens you can restore the backup.
"""

import shutil
import sqlite3
import os
import sys
from datetime import datetime

DB_PATH = os.path.join('instance', 'users.db')
BACKUP_PATH = DB_PATH + '.bak'

if not os.path.exists(DB_PATH):
    print(f"ERROR: DB not found at {DB_PATH}")
    sys.exit(1)

print(f"Backing up {DB_PATH} -> {BACKUP_PATH}")
shutil.copy2(DB_PATH, BACKUP_PATH)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Turn off foreign keys temporarily for the migration steps
cur.execute('PRAGMA foreign_keys = OFF')
conn.commit()

# Create new table with desired schema (no UNIQUE(username), keep UNIQUE(email))
print('Creating new temporary table user_new...')
cur.execute('''
CREATE TABLE user_new (
    id INTEGER PRIMARY KEY,
    username VARCHAR(80) NOT NULL,
    email VARCHAR(120),
    password_hash VARCHAR(128),
    scouting_team_number INTEGER,
    is_active BOOLEAN,
    created_at DATETIME,
    updated_at DATETIME,
    last_login DATETIME,
    profile_picture VARCHAR(256),
    must_change_password BOOLEAN
)
''')
conn.commit()

# Copy data from old user -> user_new
# Make sure columns match; this assumes the old table had the same column names.
print('Copying data from existing user table to user_new...')
cur.execute('PRAGMA table_info("user")')
cols_info = cur.fetchall()
cols = [c[1] for c in cols_info]
print(f'Existing user columns: {cols}')

# We'll copy the intersection of columns to be safe
new_cols = ['id','username','email','password_hash','scouting_team_number','is_active','created_at','updated_at','last_login','profile_picture','must_change_password']
copy_cols = [c for c in new_cols if c in cols]
if not copy_cols:
    print('No matching columns found to copy - aborting')
    conn.close()
    sys.exit(1)

col_list = ','.join(copy_cols)
placeholders = ','.join(['?'] * len(copy_cols))

# Select rows from old table
cur.execute(f"SELECT {col_list} FROM user")
rows = cur.fetchall()
print(f'Found {len(rows)} rows to copy')

# Insert into new table
cur.executemany(f"INSERT INTO user_new ({col_list}) VALUES ({placeholders})", rows)
conn.commit()

# Drop old table and rename new
print('Dropping old user table...')
cur.execute('DROP TABLE user')
conn.commit()

print('Renaming user_new -> user')
cur.execute('ALTER TABLE user_new RENAME TO user')
conn.commit()

# Recreate unique index on email (if present before)
print('Creating UNIQUE INDEX on email if not exists')
try:
    cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_user_email ON user(email)')
    conn.commit()
except Exception as e:
    print('Warning: failed to create unique index on email:', e)

# Create composite unique index on (username, scouting_team_number)
print('Creating UNIQUE INDEX on (username, scouting_team_number)')
cur.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_user_username_team ON user(username, scouting_team_number)')
conn.commit()

# Re-enable foreign keys
cur.execute('PRAGMA foreign_keys = ON')
conn.commit()

conn.close()
print('Migration completed successfully.')
print(f'Backup is available at {BACKUP_PATH} - verify before removing.')
