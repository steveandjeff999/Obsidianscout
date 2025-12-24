# Administrator Guide

Comprehensive guide for administrators managing Obsidian-Scout scouting systems.

## Admin Role Overview

As an administrator, you have full access to all system features and data. Your responsibilities include:
- **User management** (creating, editing, disabling accounts)
- **System configuration** (game config, API settings, features)
- **Data management** (backup, export, import)
- **Security** (permissions, API keys, account locks)
- **Monitoring** (sync status, errors, performance)
- **Support** (helping team members troubleshoot issues)

## User Management

### Accessing User Management

1. Click your **username** in the top-right navbar
2. Select **User Management** from dropdown
3. View all users in your scouting team

### Creating New Users

1. Click **Add New User** button
2. Fill in required fields:
   - **Username** (unique, alphanumeric, no spaces)
   - **Email** (optional, used for password recovery if configured)
   - **Scouting Team Number** (should match your team)
   - **Password** (temporary password)
3. Select **Roles**:
   - **Admin**: Full system access
   - **Analytics**: Data analysis and graphs, no user management
   - **Scout**: Data entry only, no dashboard access
4. Check **Must Change Password** (recommended for new accounts)
5. Click **Create User**

### Editing Users

1. Find user in list
2. Click **Edit** button
3. Modify:
   - Email address
   - Roles (add/remove)
   - Active status (disable without deleting)
   - Profile picture
4. Click **Save Changes**

### Resetting Passwords

**For another user:**
1. Edit user account
2. Enter new temporary password
3. Check **Must Change Password**
4. User forced to change at next login

**For yourself:**
- Use **Profile** page
- Enter current password and new password
- Or use password recovery if email configured

### Disabling Accounts

**Temporary suspension:**
1. Edit user
2. Uncheck **Is Active**
3. Save
4. User cannot log in but account data preserved

**Permanent removal:**
1. Click **Delete** button on user row
2. Confirm deletion
3. **Warning**: Cannot be undone, removes user from database
4. Consider disabling instead for audit trail

### Account Creation Lock

**Purpose:** Prevent unauthorized signups during competitions.

**To lock:**
1. Go to User Management
2. Click **Lock Account Creation** toggle
3. Banner appears on signup page
4. Only admins can create accounts

**To unlock:**
1. Click **Unlock Account Creation**
2. Public signups re-enabled (if previously allowed)

## System Configuration

### Game Configuration

**Purpose:** Defines scoring elements, metrics, and form layout for match scouting.

**Accessing:**
1. Go to **Admin Settings** > **Configuration**
2. Click **Edit Game Config** or **Simple Edit**

**Key Sections:**

#### Basic Settings
- **Game Name**: Display name (e.g., "2024 Crescendo")
- **Season**: Year (e.g., 2024)
- **Alliance Size**: Teams per alliance (typically 3)
- **Scouting Stations**: Number of positions (typically 6)
- **Match Types**: Practice, Qualification, Playoff
- **Current Event Code**: Active event (e.g., "2024cala")

#### Scoring Periods
- **Auto Period**: Autonomous scoring elements and duration
- **Teleop Period**: Teleoperated scoring elements and duration
- **Endgame Period**: Endgame actions and duration

**For each period, define:**
- Element ID (unique identifier)
- Element Name (display label)
- Element Type (counter, boolean, dropdown, rating)
- Default Value
- Points (for auto-scoring)

#### Post-Match Elements
- **Rating Elements**: 1-5 star ratings (defense, driver skill, etc.)
- **Text Elements**: Notes and comments

#### Key Metrics
- Calculated metrics for analytics
- Aggregation methods (average, sum, max, min)
- Display in predictions toggle
- Formula-based calculations

#### API Settings
- **FIRST API**: Username and auth token
- **The Blue Alliance API**: API key
- **Preferred Source**: Which API to try first
- **Auto-Sync Enabled**: Toggle automatic syncing

**Saving:**
1. Review all changes in preview
2. Click **Save Configuration**
3. Changes take effect immediately
4. Backup created automatically

### Pit Scouting Configuration

**Similar structure to game config but for pit scouting forms.**

**Location:** `config/pit_config.json`

**Editing:**
1. Go to **Admin Settings** > **Configuration** > **Pit Config**
2. Define form sections and elements
3. Save changes

### Configuration Backups

**Automatic Backups:**
- Created before every save
- Stored in `config/` folder with timestamps
- Keep last 10 backups by default

**Manual Backup:**
1. Copy `config/game_config.json` to safe location
2. Include date in filename (e.g., `game_config_2024-10-08.json`)

**Restore from Backup:**
1. Go to **Configuration** > **Reset to Default**
2. Select backup file
3. Confirm restoration
4. Or manually copy backup file over current config

## Event Management

### Creating Events

1. Go to **Events** page
2. Click **Add Event**
3. Fill in details:
   - **Event Code** (e.g., "2024cala" - must match FIRST/TBA code)
   - **Event Name** (e.g., "Chezy Champs 2024")
   - **Location** (city, state)
   - **Start/End Dates**
4. Click **Create**

### Syncing Event Data from API

**Automatic Sync:**
- If enabled in configuration, syncs every 3 minutes
- Updates teams, matches, and scores

**Manual Sync:**
1. Go to **Events** page
2. Click **Sync from API** for specific event
3. Or use **Teams** > **Sync Teams** and **Matches** > **Sync Matches**

**Troubleshooting Sync:**
- Verify API credentials in configuration
- Check event code matches FIRST/TBA exactly
- Use **Admin** > **API Testing** to diagnose
- Review sync monitor for errors

### Setting Current Event

1. Go to **Events** page
2. Click **Set as Current** next to event
3. Or edit configuration and set `current_event_code`
4. Current event determines:
   - Which teams show in forms
   - Which matches appear in strategy tools
   - Default filters for graphs/analytics

## Data Management

### Database Backups

**Critical:** Backup before competitions and after major data entry!

**Manual Backup:**
```powershell
# Windows PowerShell
Copy-Item "instance\\scouting.db" "backups\\scouting_$(Get-Date -Format 'yyyy-MM-dd_HHmm').db"

# Also backup users database
Copy-Item "instance\\users.db" "backups\\users_$(Get-Date -Format 'yyyy-MM-dd_HHmm').db"
```

**Automated Backups:**
- Set up scheduled task (Windows) or cron job (Linux/Mac)
- Run backup script daily
- Store backups on separate drive/cloud storage
- Test restores regularly

**Restore from Backup:**
1. **Stop application**
2. Replace `instance/scouting.db` with backup file
3. Replace `instance/users.db` if needed
4. **Restart application**
5. Verify data integrity

### Exporting Data

**CSV Export:**
1. Go to **Data** > **Export**
2. Select data type (scouting data, pit data, teams, matches)
3. Choose event or date range
4. Click **Export to CSV**
5. Open in Excel, Google Sheets, etc.

**API Export:**
- Use API keys for programmatic access
- See `API_DOCUMENTATION.md` for endpoints
- JSON format for integration with other tools

### Importing Data

**CSV Import:**
1. Prepare CSV file in correct format (match column headers)
2. Go to **Data** > **Import**
3. Select file and data type
4. Review preview
5. Confirm import
6. Check for errors/warnings

**QR Code Import:**
1. Generate QR codes from other systems/devices
2. Go to **Scouting** > **QR Scan**
3. Scan codes one by one
4. Data automatically imports

## API Key Management

### What are API Keys?

API keys allow external applications and scripts to access your scouting data programmatically. Use cases:
- Custom analysis scripts
- Third-party integrations
- Alliance partner data sharing
- Mobile app development

### Creating API Keys

1. Go to **Admin** > **API Keys** > **Manage**
2. Click **Create New Key**
3. Fill in details:
   - **Name**: Descriptive name (e.g., "Python Analysis Scripts")
   - **Description**: Purpose and usage notes
   - **Rate Limit**: Requests per hour (default 1000)
   - **Permissions**:
     - **Team Data Access**: Read teams/events
     - **Scouting Data Read**: View scouting entries
     - **Scouting Data Write**: Create/edit entries
     - **Sync Operations**: Trigger syncs
     - **Analytics Access**: Advanced metrics
4. Click **Generate Key**
5. **Copy key immediately** - won't be shown again!

### Managing API Keys

**View Usage:**
1. Go to API Keys list
2. Click on key name
3. View statistics:
   - Total requests
   - Last used timestamp
   - Daily usage graph
   - Recent requests log

**Revoking Keys:**
1. Find key in list
2. Click **Revoke** or **Delete**
3. Confirm action
4. Key immediately stops working

**Testing Keys:**
1. Go to **Admin** > **API Testing**
2. Enter API key
3. Run test requests
4. Verify responses

### API Key Security

- **Never share keys publicly** (GitHub, forums, etc.)
- **Rotate keys regularly** (quarterly or after events)
- **Use separate keys** for different purposes
- **Monitor usage** for suspicious activity
- **Revoke immediately** if compromised
- **Set appropriate permissions** (principle of least privilege)

## Monitoring and Diagnostics

### Sync Monitor

**Accessing:**
1. Go to **Admin** > **Sync Monitor**
2. View real-time sync statistics

**Key Metrics:**
- **Connection Status**: WebSocket connection (green = good)
- **Queue Size**: Pending operations (should be near 0)
- **Worker Status**: Background sync worker (running = good)
- **Last Sync**: Timestamp of most recent sync
- **Error Count**: Failed operations (investigate if > 0)

**Actions:**
- **Trigger Manual Sync**: Force immediate sync
- **Clear Queue**: Reset stuck operations
- **Restart Worker**: Restart background sync process

### System Health

**Database Status:**
- Check database file size (under 1GB typical)
- Monitor disk space (at least 5GB free)
- Run integrity check if issues suspected

**Application Logs:**
- Located in `logs/` folder
- `app.log`: General application events
- `error.log`: Errors and exceptions
- `sync.log`: Sync operations
- Review regularly for warnings/errors

**Performance Monitoring:**
- Watch response times (should be < 1 second for most pages)
- Monitor memory usage (Task Manager / Activity Monitor)
- Check CPU usage (spikes during sync normal)

### Error Investigation

**When errors occur:**
1. Note exact error message and time
2. Check application logs at that timestamp
3. Review browser console (F12) for client-side errors
4. Check sync monitor for sync-related issues
5. Verify network connectivity
6. Review recent configuration changes

**Common Error Patterns:**
- **5xx errors**: Server-side issues (check logs, restart if needed)
- **4xx errors**: Client-side issues (permissions, invalid requests)
- **Timeout errors**: Network or performance issues
- **Database errors**: Corruption, locking, or schema issues

## Security Best Practices

### Password Policies

- **Enforce strong passwords** for admin accounts
- **Use "Must Change Password"** for new users
- **Don't share admin credentials**
- **Change default passwords** immediately (superadmin, admin)
- **Disable unused accounts** promptly

### Role Assignment

- **Follow principle of least privilege** (minimum role needed)
- **Limit admin role** to team leadership only
- **Review roles regularly** (before/after events)
- **Remove roles** when members leave team

### Network Security

- **Use HTTPS** for public deployments (SSL certificates)
- **Firewall configuration** (restrict unnecessary ports)
- **Private network** for internal use (no public internet)
- **VPN** for remote access if needed
- **IP whitelisting** for API access

### Data Protection

- **Regular backups** (automated if possible)
- **Offsite backup storage** (cloud or separate location)
- **Test restores** regularly
- **Limit data export** to trusted individuals
- **Anonymize data** when sharing publicly

## Troubleshooting Guide

See `TROUBLESHOOTING.md` for comprehensive troubleshooting, but quick admin-specific tips:

### Users Can't Log In
- Verify account is active (User Management)
- Check password reset if forgotten
- Ensure scouting team number correct
- Check account creation lock if new user

### Data Not Syncing
- Check sync monitor for errors
- Verify network connectivity
- Test API credentials (API Testing tool)
- Force manual sync
- Review sync logs

### Performance Issues
- Check database size (archive old data if > 1GB)
- Monitor concurrent users (limit if too many)
- Restart application (daily during events recommended)
- Check server resources (CPU, RAM, disk)

### Configuration Not Saving
- Verify JSON syntax (use validator)
- Check file permissions (write access needed)
- Review error logs for specific issue
- Try backup/restore approach

## Pre-Competition Checklist

**1 Week Before:**
- [ ] Backup all databases
- [ ] Update application to latest version
- [ ] Test API sync with event code
- [ ] Configure game config for current game
- [ ] Train scouts on form layout
- [ ] Create user accounts for event personnel
- [ ] Test all devices (tablets, laptops, phones)

**1 Day Before:**
- [ ] Sync teams and matches from API
- [ ] Verify network setup at venue
- [ ] Test real-time sync between devices
- [ ] Review roles and permissions
- [ ] Prepare pit scouting assignments
- [ ] Backup again

**Event Day:**
- [ ] Arrive early to set up network
- [ ] Verify internet connectivity
- [ ] Test all device logins
- [ ] Sync latest match schedule
- [ ] Monitor sync status throughout day
- [ ] Backup database at lunch and end of day

## Post-Competition Tasks

- [ ] Final database backup
- [ ] Export data to CSV for archival
- [ ] Generate competition report/summary
- [ ] Review logs for any recurring issues
- [ ] Deactivate event-specific user accounts
- [ ] Thank team members for their effort
- [ ] Document lessons learned
- [ ] Prepare data for off-season analysis

## Advanced Administration

### Custom Widget Development
- See `CUSTOM_WIDGET_GUIDE.md` for creating custom dashboard widgets
- Requires Python knowledge
- Test in dev environment first

### Server-to-Server Sync
- See `CONNECTIONS_AND_SYNC.md` for multi-instance setup
- Useful for large teams with multiple locations
- Requires network configuration and API keys

### Database Optimization
```powershell
# Run VACUUM to reclaim space
sqlite3 instance/scouting.db
```
```sql
VACUUM;
.quit
```

### Alliance Configuration
- Set up scouting alliances before playoff matches
- Manage invitations and permissions
- Monitor alliance sync status
- Revoke access after competition if needed

**Tip:** You can use the inline help icons (question-mark) next to headings throughout the Alliances UI to get quick contextual guidance. Toggle these icons in **Settings → Show inline help icons** if you want to hide them.


## Getting Help

### Resources
- **Help Documentation**: All MD files in `help/` folder
- **API Documentation**: `API_DOCUMENTATION.md`
- **Troubleshooting Guide**: `TROUBLESHOOTING.md`
- **GitHub Repository**: https://github.com/steveandjeff999/Obsidianscout

### Support Channels
- **GitHub Issues**: Report bugs and request features
- **Team Tech Lead**: Escalate to team's technical leadership
- **FRC Community**: Chief Delphi, Discord servers
- **Documentation**: Continuously updated based on feedback

### Contributing Back
- Document team-specific configurations
- Share lessons learned with community
- Report bugs with detailed reproduction steps
- Suggest feature improvements
- Contribute code if comfortable with Python/Flask

## Conclusion

Admin responsibilities are critical to a successful scouting operation. Focus on:
- **Preparation**: Test and configure before events
- **Monitoring**: Watch for issues during competition
- **Communication**: Keep team informed of any issues
- **Documentation**: Record configurations and procedures
- **Security**: Protect data and access carefully

With proper administration, Obsidian-Scout provides a robust platform for competitive FRC scouting! 
