# Administrator Guide (Web Only)

This guide covers administrator actions available from the web interface only.

## Admin responsibilities

- Manage users and roles
- Configure scouting forms and system settings
- Manage events and sync settings
- Review data quality and exports
- Monitor system health from admin pages

## User Management

Open from your user menu: **User Management**.

### Create users

1. Click **Add New User**
2. Enter username, team number, and temporary password
3. Assign role(s): **Admin**, **Analytics**, **Scout**
4. Enable **Must Change Password**
5. Save

### Edit or disable users

1. Find user in the list
2. Click **Edit**
3. Update role, email, or active status
4. Save

Use **disable** instead of delete when you need account history preserved.

### Reset user passwords

1. Open user **Edit**
2. Set temporary password
3. Enable **Must Change Password**
4. Save

### Lock account creation

In User Management, use the account creation lock toggle to prevent open signups during events.

## Configuration

Open: **Admin Settings -> Configuration**.

### Game configuration

Use the editor to manage:

- game/season basics
- scouting periods (auto, teleop, endgame)
- scoring elements and defaults
- post-match ratings/notes
- key metrics and calculations

Save changes and verify scouting forms update as expected.

### Pit scouting configuration

Use the pit config editor to control pit form fields and sections.

### API settings

From configuration, set:

- primary API provider
- fallback API provider
- credentials
- auto-sync toggle

Run API tests from the admin pages after saving.

## Event Management

Open: **Events**.

### Create and maintain events

1. Click **Add Event**
2. Enter code, name, location, and dates
3. Save

### Set current event

Select **Set as Current** on the event you are actively scouting.

### Sync event data

Use event/team/match sync actions in the web UI to pull updated schedules and team lists.

## Data Management (Web)

### Export data

Open: **Data -> Export**.

- Choose data type
- Apply event/date filters
- Export for analysis

### Import data

Open: **Data -> Import**.

- Upload supported file format
- Review preview
- Confirm import

You can also import scouting entries through the QR scanning pages.

## Monitoring and support

### Sync and status

Use admin monitoring pages to check:

- connection health
- sync queue/status
- recent failures

### Fast support flow

When users report issues:

1. Verify role and account status
2. Verify current event selection
3. Check sync/connection health
4. Re-test the action in browser

For common user-facing fixes, see `TROUBLESHOOTING.md`.

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


