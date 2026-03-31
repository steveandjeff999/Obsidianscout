# Troubleshooting

Use this page for fast diagnosis before deep debugging.

## 1) Login issues

- Confirm username/password and correct scouting team number
- Ask admin to verify account is active and role is assigned
- Log out, clear browser cache/cookies, and log in again

If needed:

```powershell
python reset_superadmin.py
```

Alternative admin reset helper:

```powershell
python other\reset_admin.py
```

## 2) Data not saving

- Check connection status indicator in the app
- Refresh and submit again
- Confirm your session did not expire
- Verify your role has permission for that action

## 3) App not loading correctly

- Hard refresh (`Ctrl+Shift+R`)
- Try another browser
- Confirm server is running (`python run.py`)

## 4) Database locked errors

- Stop all running app instances
- Wait a few seconds, then start one instance only
- Check for leftover lock/journal files in `instance/`

## 5) Missing table or schema mismatch

- Restore from backup if available
- Run migrations/upgrade steps for your deployment
- Recreate only if this is a fresh setup

## 6) API sync problems

- Verify credentials in API settings
- Test with a known event code
- Enable fallback API source if primary is failing

## 7) When to escalate

Escalate to admin/developer if:

- errors persist after restart and relogin
- multiple users report the same failure
- database integrity/corruption is suspected

For sync-specific behavior, see `CONNECTIONS_AND_SYNC.md`.

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

# Copy one of the default game config templates for your season from config\defaults\
# Example workflow:
dir config\\defaults\\*config*.json
# then copy the correct seasonal file to config\\game_config.json
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
python other/init_auth.py
```

### 4. Can't login as admin or superadmin

**Solution:**
There are two convenience accounts used during setup:

- `superadmin` — auto-created by `run.py` on first run if no users exist. Default password is `password` and the account is created with `must_change_password=False`.
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
3. Run `python other/init_auth.py` to recreate the database

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
python other/init_auth.py
```
