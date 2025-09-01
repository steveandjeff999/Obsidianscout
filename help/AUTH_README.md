# Authentication System Documentation

## Overview
This document explains how to use the authentication system in the ObsidianScout application.

## User Roles

The system supports three user roles with different permissions:

- **Admin:** Full access to all features and settings.
- **Analytics:** Can view and analyze data, but cannot change settings.
- **Scout:** Can enter and view scouting data, limited access to admin features.

1. **Admin**
    - Full system access
    - Can manage users
    - Can configure system settings
    - Default admin account: the project includes a helper script to create/reset an `admin` user (`other/reset_admin.py`). The script creates or resets an `admin` account with these credentials:
       - Username: `admin`
       - Password: `password`
       - Run: `python other/reset_admin.py`
    - Note: The application also auto-creates a `superadmin` account on first run when no users exist (see "Getting Started" below).

2. **Analytics**
   - Access to data analysis features
   - Access to visualization and graphs
   - Access to team and match data
   - Cannot manage users

3. **Scout**
   - Limited access to scouting features only
   - Can enter match data
   - Can view their own scouting records
   - Cannot access the main dashboard
   - Cannot access analytics or data management
   - Automatically redirected to scouting page after login

## Getting Started

1. Initialize the authentication system:
    ```
    python init_auth.py
    ```

    This will create the necessary roles. Default accounts are handled as follows:

    - On first run, `run.py` automatically attempts to create a `superadmin` account if no users exist. That account uses:
       - Username: `superadmin`
       - Password: `password`
       - Team Number: `0`
       - The created `superadmin` has `must_change_password=True` so the user must change the password on first login.

    - The `other/reset_admin.py` script is provided to create or reset an `admin` account (username `admin`, password `password`) at any time:
       ```
       python other/reset_admin.py
       ```

2. Log in with the admin account and create additional users as needed.

## Adding Users

1. Log in as an admin user
2. Navigate to the User Management page from the user dropdown menu
3. Click "Add User"
4. Fill out the username, email (optional), password, and select roles
5. Click "Create User"

## Managing Roles

Users can have multiple roles. For example, a user can be both an admin and an analytics user.

- **Admin users** have access to everything in the system
- **Analytics users** have access to all data features but cannot manage users
- **Scout users** can only access the scouting page

## Security Notes

1. Passwords are securely hashed and stored using werkzeug's password hashing
2. User sessions are managed via Flask-Login with secure cookies
3. After account creation, users can update their own profiles

## Role-Based Access Control

The navigation menu and page access are controlled by user roles:

- Scouting menu: Visible to all authenticated users
- Analytics, Teams, Matches, etc.: Visible only to admin and analytics users
- User Management: Visible only to admin users
