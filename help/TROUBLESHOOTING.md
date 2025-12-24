# Troubleshooting Guide for 5454Scout Authentication System

## Quick Troubleshooting

### Can't log in
- Check your username and password.
- Make sure your account is active.

### Data not saving
- Check your internet connection.
- Try refreshing the page.

### Still stuck?
Contact your system administrator for further help.

## Common Issues and Solutions

```markdown
# Obsidian-Scout Troubleshooting Guide

Comprehensive troubleshooting guide for common issues and their solutions.

## Quick Fixes

### Can't Log In
- **Check username and password** (case-sensitive)
- Verify **account is active** (admins can check user management)
- Clear browser **cookies and cache**
- Try **incognito/private mode** to rule out extension conflicts
- Ensure **scouting team number** is correct on login form

### Data Not Saving
- Check **internet connection** (look for connection indicator in navbar)
- Try **refreshing the page** (Ctrl+R or Cmd+R)
- Verify you're still **logged in** (session may have expired)
- Check if you have **permission** to edit (Scout vs. Analytics vs. Admin)
- Look for **error messages** in red banner at top of page

### Page Not Loading / Errors
- **Hard refresh**: Ctrl+Shift+R (Cmd+Shift+R on Mac)
- **Clear browser cache**: Settings > Privacy > Clear Data
- Try **different browser** (Chrome recommended)
- Check **browser console** for JavaScript errors (F12)
- Verify **server is running** (check URL/port)

## Authentication Issues

### 1. UNIQUE Constraint Failed on user.email

**Error Message:**
```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed: user.email
```

**Cause:** Multiple users with empty email addresses (NULL vs empty string inconsistency).

**Solution:**
```powershell
python fix_emails.py
```

This converts empty strings to NULL, allowing multiple users without emails.

### 2. Can't Login as Superadmin

**Default Credentials:**
- Username: `superadmin`
- Password: `password` (must change on first login)
- Auto-created by `run.py` on first run

**If superadmin doesn't exist:**
```powershell
python run.py
```
First run creates superadmin automatically.

**Reset superadmin password:**
```powershell
python reset_superadmin.py
```

### 3. Can't Login as Admin

**Reset admin account:**
```powershell
python other/reset_admin.py
```
Creates/resets admin user with password: `password`

**Manual reset via Python:**
```python
from app import create_app, db
from app.models import User

app = create_app()
with app.app_context():
    user = User.query.filter_by(username="admin").first()
    if user:
        user.set_password("password")
        db.session.commit()
        print("Password reset successfully")
```

### 4. Account Creation Locked

**Symptom:** Can't create new accounts, get "Account creation locked" message.

**Solution (Admin only):**
1. Log in as admin
2. Go to **User Management**
3. Click **Unlock Account Creation** toggle
4. New accounts can now be created

### 5. Role-Based Access Not Working

**Symptoms:**
- Can't access pages that should be available
- Redirected unexpectedly
- Features missing from navbar

**Solutions:**
1. **Check roles assigned**: User Management > Edit User > Verify roles
2. **Log out and back in**: Roles cached in session
3. **Clear cookies**: May have stale session data
4. **Verify team isolation**: Users only see their scouting team's data

**Role Permissions Reference:**
- **Admin**: Full access
- **Analytics**: All data/graphs, no user management
- **Scout**: Scouting forms only, no dashboard

### 6. Must Change Password Loop

**Symptom:** Forced to change password repeatedly after changing it.

**Cause:** `must_change_password` flag not clearing.

**Solution (Admin):**
```powershell
python
```
```python
from app import create_app, db
from app.models import User

app = create_app()
with app.app_context():
    user = User.query.filter_by(username="problematic_user").first()
    user.must_change_password = False
    db.session.commit()
```

## Database Issues

### 7. Database is Locked

**Error Message:**
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
```

**Causes:**
- Multiple processes accessing database simultaneously
- Previous crash left lock file
- Antivirus scanning database file

**Solutions:**

**Immediate fix:**
1. Stop all running instances of the application
2. Wait 10 seconds for lock release
3. Delete `instance/scouting.db-journal` if it exists
4. Restart application

**Persistent issues:**
1. Check for multiple `run.py` processes: Task Manager (Windows) or Activity Monitor (Mac)
2. Disable antivirus real-time scanning on `instance/` folder
3. Move database to faster storage (not network drive)

**Enable WAL mode (recommended):**
Database uses WAL (Write-Ahead Logging) mode automatically. Verify:
```powershell
sqlite3 instance/scouting.db
```
```sql
PRAGMA journal_mode;
```
Should return `wal`. If not:
```sql
PRAGMA journal_mode=WAL;
.quit
```

### 8. No Such Table Errors

**Error Message:**
```
sqlalchemy.exc.OperationalError: no such table: <table_name>
```

**Cause:** Database schema not created or outdated.

**Solution:**

**Re-initialize database:**
```powershell
# Backup existing data first!
copy instance\\scouting.db instance\\scouting.db.backup

# Recreate tables
python
```
```python
from app import create_app, db

app = create_app()
with app.app_context():
    db.create_all()
```

**Use migrations (if available):**
```powershell
flask db upgrade
```

### 9. Database Corruption

**Symptoms:**
- Random errors during queries
- Data disappearing
- Application crashes
- Integrity check failures

**Diagnosis:**
```powershell
sqlite3 instance/scouting.db
```
```sql
PRAGMA integrity_check;
.quit
```

**Recovery steps:**
1. **Stop application immediately**
2. **Backup corrupted database**: `copy instance\\scouting.db instance\\scouting_corrupt.db`
3. **Attempt recovery**:
```powershell
sqlite3 instance/scouting_corrupt.db
```
```sql
.output instance/recovered.sql
.dump
.quit

sqlite3 instance/scouting_new.db
.read instance/recovered.sql
.quit
```
4. **Replace database**: `copy instance\\scouting_new.db instance\\scouting.db`
5. **Restart application**

**If recovery fails:**
- Restore from backup (should backup daily!)
- Re-sync from API (teams/matches)
- Manual data re-entry (scouting data)

## Configuration Issues

### 10. Game Configuration Not Loading

**Symptoms:**
- Scouting forms blank or missing fields
- Metrics not calculating
- Error: "Game config not found"

**Solutions:**

**Verify config file exists:**
```powershell
dir config\\game_config.json
```

**Check JSON validity:**
- Copy contents to https://jsonlint.com
- Fix any syntax errors (missing commas, brackets)

**Reset to default:**
```powershell
# Backup current config
copy config\\game_config.json config\\game_config_backup.json

# Copy from defaults (choose your game)
copy config\\defaults\\2024_crescendo_config.json config\\game_config.json
```

**Re-load config (without restart):**
1. Go to **Admin Settings** > **Configuration**
2. Click **Reload Configuration**
3. Verify changes appear

### 11. Pit Configuration Issues

**Similar to game config, but for pit scouting.**

**File location:** `config/pit_config.json`

**Reset to default:**
```powershell
copy config\\defaults\\default_pit_config.json config\\pit_config.json
```

### 12. API Credentials Not Working

**Symptoms:**
- Teams/matches not syncing
- "API authentication failed" errors
- Empty event data

**Check configuration:**
1. Go to **Admin Settings** > **Configuration** > **API Settings**
2. Verify credentials entered correctly (no extra spaces)
3. Test with **API Testing** tool (Admin menu)

**FIRST API issues:**
- Verify credentials at https://frc-events.firstinspires.org/services/API
- Check authorization token hasn't expired
- Ensure account has API access enabled

**The Blue Alliance issues:**
- Get/regenerate API key at https://www.thebluealliance.com/account
- Verify key format (starts with alphanumeric string)
- Check rate limits not exceeded

**Fallback to secondary API:**
- Set **Preferred API Source** to alternate API
- System automatically tries fallback if primary fails

## Sync and Connection Issues

### 13. Real-Time Sync Not Working

**Symptoms:**
- Data not appearing on other devices
- Chat messages not sending
- Strategy drawings not syncing

**Diagnosis:**
1. Check **connection indicator** in navbar (should be green)
2. Go to **Admin** > **Sync Monitor**
3. Look for WebSocket connection status

**Solutions:**

**Firewall blocking WebSocket:**
- Whitelist application port (default 8080)
- Allow outbound connections to server IP
- Check corporate/school firewall rules

**Network issues:**
- Verify all devices on same network
- Check Wi-Fi signal strength
- Try wired Ethernet connection
- Restart router/access point

**Force reconnect:**
- Refresh page (F5)
- Log out and back in
- Restart browser
- Clear browser cache

### 14. Catch-Up Sync Failures

**Symptoms:**
- Offline data not syncing when back online
- "Catch-up sync failed" errors
- Queue size increasing

**Solutions:**

**Manual trigger:**
1. Go to **Admin** > **Sync Monitor**
2. Click **Trigger Catch-Up Sync**
3. Monitor progress

**Clear stuck queue:**
```powershell
# Stop application
# Delete queue file
del instance\\catchup_queue.json
# Restart application
```

**Check server logs:**
```powershell
type logs\\sync.log
```
Look for specific error messages.

### 15. Alliance Sync Not Working

**Symptoms:**
- Alliance partner data not visible
- Invitation not received
- "Sync failed" for alliance

**Solutions:**

**Verify alliance membership:**
1. Go to **Alliances** > **Scouting Alliances**
2. Check status shows "Accepted"
3. Ensure current event matches alliance event

**Check help icons and popovers:**
- If the small question-mark help icons do not show popovers, verify that **Show inline help icons** is enabled in **Settings**.
- Ensure JavaScript is enabled and your browser supports Bootstrap popovers (modern Chrome/Edge/Firefox recommended).
- If popovers still fail, check browser console for JS errors and report via the support channel.


**Re-invite member:**
- Remove member from alliance
- Wait 30 seconds
- Re-add member
- Have them accept invitation again

**Check server connectivity:**
- Alliance partners must be on same network OR
- Both servers must have public IPs with ports open
- Test ping between servers

## Forms and Data Entry Issues

### 16. Scouting Form Not Loading

**Symptoms:**
- Blank form
- "Loading..." never completes
- Form elements missing

**Solutions:**

**Check event selected:**
- Verify current event set in configuration
- Go to **Admin** > **Configuration**
- Set **current_event_code** to active event

**Verify teams exist:**
- Go to **Teams** page
- If empty, sync from API
- Click **Sync Teams** button

**Check game config:**
- See #10 above (Game Configuration Not Loading)

**Browser compatibility:**
- Use Chrome, Edge, or Firefox (latest version)
- Disable browser extensions
- Try incognito/private mode

### 17. Counter Buttons Not Working

**Symptom:** Plus/minus buttons on counters don't increment/decrement.

**Solutions:**
- Check JavaScript enabled in browser
- Clear browser cache
- Update browser to latest version
- Check browser console for errors (F12)

### 18. QR Code Scanning Not Working

**Symptoms:**
- Camera not activating
- QR code not detected
- "Camera permission denied"

**Solutions:**

**Grant camera permissions:**
- **Chrome**: Click camera icon in address bar > Allow
- **Safari**: Settings > Websites > Camera > Allow
- **Firefox**: Click camera icon in address bar > Allow

**Camera issues:**
- Ensure device has camera
- Check camera works in other apps
- Try different browser
- Restart device

**QR code issues:**
- Increase QR code size on display
- Ensure good lighting (no glare/shadows)
- Hold steady for 2-3 seconds
- Try generating QR code again

**Alternative:** Use Data Matrix format (supports more data)

### 19. Photo Upload Failing

**Symptoms:**
- "Upload failed" error
- Photo not appearing after upload
- Progress bar stuck

**Solutions:**

**Check file size:**
- Max 5MB per photo
- Compress large images before upload
- Use lower resolution from camera settings

**Check file format:**
- Supported: JPG, PNG, GIF
- Convert other formats (HEIC, BMP, TIFF)

**Check upload folder permissions:**
```powershell
# Verify folder exists and writable
dir instance\\uploads
# If doesn't exist:
mkdir instance\\uploads
```

**Storage space:**
- Check disk space on server
- Clean up old uploads if needed

## Graph and Analysis Issues

### 20. Graphs Not Displaying

**Symptoms:**
- Blank graph area
- "No data available"
- Graph never loads

**Solutions:**

**Verify data exists:**
- Check scouting data entered for selected teams
- Go to **Scouting** > **List** to confirm
- Ensure selected metric exists in game config

**Check metric selection:**
- Some metrics only available with sufficient data
- Try different metric
- Use "Total Points" for universal metric

**Browser issues:**
- Enable JavaScript
- Update browser
- Clear cache
- Try different browser (Chrome recommended)

**Plotly loading issues:**
- Check internet connection (Plotly loads from CDN)
- Whitelist CDN domains in firewall
- Check browser console for 404 errors

### 21. Side-by-Side Comparison Empty

**Symptom:** Comparison table shows no data for teams.

**Solutions:**
- Verify teams have scouting data entered
- Check event filter - may be filtering out all data
- Ensure teams are in current event
- Try refreshing page

### 22. Custom Pages/Widgets Not Working

**Symptoms:**
- Widget shows error
- Custom code not executing
- Page layout broken

**Solutions:**

**Check widget code:**
- Go to **Graphs** > **Custom Pages** > Edit Page
- Review custom widget code for syntax errors
- Check browser console for JavaScript errors

**Verify data access:**
- Ensure widget has correct permissions
- Check scouting team isolation
- Verify metric IDs match game config

**Reset widget:**
- Delete problematic widget
- Re-add from scratch
- Use built-in widgets first to test

## Performance and Stability Issues

### 23. Application Slow/Unresponsive

**Symptoms:**
- Pages take long time to load
- Forms lag when typing
- Timeouts and errors

**Causes & Solutions:**

**Large database:**
- Archive old events
- Delete test/duplicate data
- Run VACUUM on database:
```powershell
sqlite3 instance/scouting.db
```
```sql
VACUUM;
.quit
```

**Too many concurrent users:**
- Increase server resources (RAM, CPU)
- Limit concurrent sessions
- Use queue system for data entry

**Slow network:**
- Use wired Ethernet instead of Wi-Fi
- Ensure adequate bandwidth
- Check for network congestion

**Background processes:**
- Sync workers consuming resources
- Check Task Manager / Activity Monitor
- Adjust sync frequency in config

### 24. Application Crashes/Restarts

**Symptoms:**
- Application exits unexpectedly
- "500 Internal Server Error"
- Must restart to recover

**Diagnosis:**
```powershell
# Check application logs
type logs\\app.log

# Check Python errors
type logs\\error.log
```

**Common causes:**

**Memory issues:**
- Monitor RAM usage
- Restart application daily
- Increase available memory

**Unhandled exceptions:**
- Review error logs for tracebacks
- Report bugs on GitHub
- Update to latest version

**Database issues:**
- Check for corruption (see #9)
- Ensure adequate disk space
- Verify file permissions

## Miscellaneous Issues

### 25. PWA (Progressive Web App) Issues

**Symptoms:**
- Can't install app on device
- Offline mode not working
- Service worker errors

**Solutions:**

**Installation:**
- Use Chrome or Edge (best PWA support)
- Look for install icon in address bar
- iOS: Safari > Share > Add to Home Screen

**Offline functionality:**
- Clear service worker cache
- Unregister and re-register service worker
- Check browser console for SW errors

**Update issues:**
- Uninstall PWA
- Clear browser data
- Re-install from browser

### 26. Chat Not Working

**Symptoms:**
- Messages not sending
- Can't see other users
- Group chat empty

**Solutions:**

**Check WebSocket connection:**
- See #13 (Real-Time Sync Not Working)
- Verify firewall rules

**User isolation:**
- Can only chat with users in same scouting team
- Verify team number matches

**Chat history:**
- May need to refresh to load history
- Check `instance/chat/` folder exists
- Verify file permissions

### 27. Search Not Finding Results

**Symptoms:**
- Search returns no results
- Known teams/data not appearing

**Solutions:**

**Verify data exists:**
- Check teams/matches directly
- Ensure data in database

**Team isolation:**
- Search scoped to your scouting team
- Won't find data from other teams

**Clear search index:**
- Clear browser cache
- Restart application
- Re-sync data from API

## Getting Additional Help

### Before Contacting Support

1. **Check this guide thoroughly**
2. **Review relevant documentation** (`API_DOCUMENTATION.md`, `CONNECTIONS_AND_SYNC.md`, etc.)
3. **Check application logs** (in `logs/` folder)
4. **Browser console** (F12) for client-side errors
5. **Try incognito mode** to rule out cache/extension issues

### Information to Provide

When reporting issues, include:
- **Exact error message** (screenshot if possible)
- **Steps to reproduce**
- **Browser and version** (e.g., Chrome 120)
- **Operating system** (Windows 11, macOS 14, etc.)
- **User role** (Admin, Analytics, Scout)
- **Relevant log excerpts**
- **Network setup** (local, Wi-Fi, multiple servers, etc.)

### Support Channels

- **GitHub Issues**: https://github.com/steveandjeff999/Obsidianscout/issues
- **Team Admin**: Contact your team's admin or tech lead
- **Documentation**: Check other help files for specific features
- **Community**: FRC Scouting communities on Chief Delphi, Discord

## Preventive Maintenance

### Regular Tasks

**Daily (During Events):**
- Backup database before start of day
- Monitor sync status
- Check disk space
- Review error logs

**Weekly:**
- Archive old/test data
- Update application if new version available
- Test backups (restore to verify)
- Review user accounts and roles

**Monthly/Off-Season:**
- Full database backup
- Clean up uploads folder
- Update documentation with lessons learned
- Train new team members on system

### Best Practices

- **Always backup before major changes**
- **Test in dev environment first**
- **Keep application updated**
- **Monitor logs regularly**
- **Document team-specific configurations**
- **Train multiple admins** (avoid single point of failure)

```

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

### 4. Can't login as admin or superadmin

**Solution:**
There are two convenience accounts used during setup:

- `superadmin` — auto-created by `run.py` on first run if no users exist. Default password is `password` and the account is created with `must_change_password=True` so you will be prompted to change it at first login.
- `admin` — can be created or reset at any time using the helper script located at `other/reset_admin.py`:

```
python other/reset_admin.py
```

The reset script will create or update the `admin` user with these credentials:
- Username: `admin`
- Password: `password`

If you still cannot log in after using the script, check application logs for errors and ensure the database exists and is accessible.

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
