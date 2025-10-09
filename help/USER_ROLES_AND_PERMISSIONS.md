# User Roles and Permissions

Obsidian-Scout uses a role-based access control system to manage user permissions and ensure data security across scouting teams.

## Available Roles

### Admin
- **Full system access** to all features and data
- Can manage users, roles, and team settings
- Access to configuration management (game config, pit config, API settings)
- Can create and manage API keys
- Can access database administration tools
- View all analytics, graphs, and strategy tools
- Manage events, teams, and matches
- Full scouting data access (create, read, update, delete)

### Analytics
- Access to all data analysis and reporting features
- Can view and create graphs, custom pages, and widgets
- Access to match strategy analysis and predictions
- Can perform side-by-side team comparisons
- View all scouting data (read-only)
- Access to pit scouting data
- **Cannot** manage users or modify system settings
- **Cannot** access database administration

### Scout
- **Limited access** designed for data entry personnel
- Can enter scouting data during matches
- Can enter pit scouting data
- Access to QR code scanning and data matrix features
- Can view their own submitted entries
- **Cannot** access the main dashboard
- **Cannot** view analytics or graphs
- **Cannot** manage users or settings
- Automatically redirected to scouting form on login

## Team Isolation

All users are assigned to a **scouting_team_number** which enforces data isolation:
- Users can only see data from their own scouting team
- Team-specific chat rooms and group messaging
- API keys are scoped to specific teams
- Alliance sync features respect team boundaries

## Managing Roles

### Assigning Roles (Admin Only)
1. Navigate to **User Management** from the user dropdown menu
2. Select a user to edit
3. Check/uncheck role assignments
4. Save changes - roles take effect immediately

### Account Creation Lock
Admins can lock account creation for their team to prevent unauthorized signups:
- Go to User Management
- Toggle "Lock Account Creation"
- Only existing admins can unlock

## Special Notes

### Must Change Password
- New accounts created with default passwords have the `must_change_password` flag set
- Users are forced to change password on first login
- Enhances security for team accounts

### Role Combinations
Users can have multiple roles simultaneously:
- A user with both **Scout** and **Analytics** roles will have Analytics-level access
- Admin role always grants highest permissions regardless of other roles

## Best Practices
- Assign the minimum required role for each user's tasks
- Review user roles regularly (especially before competitions)
- Use Scout role for data entry personnel at events
- Assign Analytics role to strategy team members
- Limit Admin role to team leadership only
- Enable account creation lock during competitions to prevent disruption 