# Authentication System Documentation

## Overview
This document explains how to use the authentication system in the 5454Scout2026 application.

## User Roles

The system supports three user roles with different permissions:

1. **Admin**
   - Full system access
   - Can manage users
   - Can configure system settings
   - Username: `admin`, Password: `password` (default admin)

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

   This will create the necessary roles and the default admin user:
   - Username: admin
   - Password: password

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
