# Troubleshooting Guide for 5454Scout Authentication System

## Common Issues and Solutions

### 1. UNIQUE constraint failed on user.email

**Error Message:**
```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed: user.email
```

**Solution:**
This happens when trying to create users with empty email fields. Run the fix script:
```
python fix_emails.py
```

This script converts empty email strings to NULL in the database, allowing multiple users without emails.

### 2. Database is locked

**Error Message:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
```

**Solution:**
This typically happens when multiple processes are accessing the database simultaneously:
1. Stop all running instances of the application
2. Wait a few seconds for the lock to be released
3. Restart the application

### 3. No such table: user

**Error Message:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: user
```

**Solution:**
The database schema hasn't been created. Run the initialization script:
```
python init_auth.py
```

### 4. Can't login as admin

**Solution:**
If you can't log in with the default admin account:
```
python reset_admin.py
```

This will create or reset the admin user:
- Username: admin
- Password: password

### 5. Unable to add new users

**Possible causes and solutions:**
- **Duplicate username**: Choose a different username
- **Duplicate email**: Use a different email or leave blank
- **No roles selected**: At least one role must be selected

### 6. Role-based access not working correctly

If users can't access pages they should have permission for:
1. Check if they have the appropriate roles assigned
2. Try clearing browser cookies and cache
3. Log out and log back in

### 7. Error after database changes

If you make changes to the models.py file or database structure:
1. Back up your existing database
2. Delete the database file: `instance/scouting.db`
3. Run `python init_auth.py` to recreate the database

## Advanced Troubleshooting

### SQLite Database Inspection

To directly inspect the database:
```
sqlite3 instance/scouting.db
```

Useful SQLite commands:
```
.tables                   -- List all tables
.schema user              -- Show user table structure
SELECT * FROM user;       -- Show all users
SELECT * FROM role;       -- Show all roles
.quit                     -- Exit SQLite
```

### Manual Database Fix

If the fix script doesn't work, you can manually fix the database:
```
sqlite3 instance/scouting.db
UPDATE user SET email = NULL WHERE email = '';
.quit
```

### Completely Reset Authentication

If you want to start fresh with authentication:
```
sqlite3 instance/scouting.db
DELETE FROM user;
DELETE FROM user_roles;
.quit
python init_auth.py
```
