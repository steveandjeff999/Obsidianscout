# Notification System Fixes - Summary

## Date: October 11, 2025

## Issues Fixed

### 1. ✅ Service Worker Registration Error
**Problem:** Service worker failed to register with error:
```
Failed to register a ServiceWorker for scope ('https://192.168.1.130:8080/') 
with script ('https://192.168.1.130:8080/sw.js'): 
An unknown error occurred when fetching the script.
```

**Root Cause:** Missing proper MIME type header for JavaScript file

**Solution:** Updated service worker route in `app/__init__.py`:
- Added `Content-Type: application/javascript; charset=utf-8` header
- Fixed path resolution to use `os.path.join(app.root_path, '..', 'sw.js')`
- Maintained cache-control headers to ensure updates are loaded

**Files Modified:**
- `app/__init__.py` (lines 790-808)

---

### 2. ✅ Email Notifications with Match Predictions
**Problem:** Email notifications didn't contain actual match predictions and strategy analysis

**Solution:** Enhanced `create_strategy_notification_message()` function to include:
- **Alliance Analysis:**
  - Team-by-team performance breakdown
  - Average auto points per match
  - Average teleop points per match
  - Total average points per match
  
- **Opponent Analysis:**
  - Same detailed breakdown for opposing alliance
  - Historical performance data from scouting entries
  
- **Match Prediction:**
  - Calculated predicted scores for both alliances
  - Win probability based on historical averages
  - Point differential prediction
  - "Too close to call" notification for even matches

**Example Output:**
```
Match qual 15 starting soon!

Team 5454 is on Red Alliance
Red Alliance: 5454, 1234, 5678
Blue Alliance: 9012, 3456, 7890

Scheduled: 02:30 PM

--- MATCH ANALYSIS ---

Red Alliance Analysis:
  Team 5454: ~45.2 pts/match (Auto: 15.3, Teleop: 29.9)
  Team 1234: ~38.7 pts/match (Auto: 12.1, Teleop: 26.6)
  Team 5678: ~42.5 pts/match (Auto: 14.8, Teleop: 27.7)

Blue Alliance Analysis:
  Team 9012: ~41.3 pts/match (Auto: 13.5, Teleop: 27.8)
  Team 3456: ~35.2 pts/match (Auto: 11.2, Teleop: 24.0)
  Team 7890: ~39.8 pts/match (Auto: 13.1, Teleop: 26.7)

Predicted Score:
  Red: 126 points
  Blue: 116 points

🎯 Prediction: Red Alliance wins by 10 points
```

**Files Modified:**
- `app/utils/notification_service.py` (lines 32-130)

---

### 3. ✅ Test Email with Random Match Prediction
**Problem:** Test email notifications were generic and didn't demonstrate the prediction system

**Solution:** Enhanced `/test-email` endpoint to:
- Fetch current event from game configuration
- Select a random match from the event
- Pick a random team from that match
- Generate a full match strategy prediction
- Include it in the test email as a demonstration

**Test Email Format:**
```
Hello username!

This is a test notification from the ObsidianScout notification system.

If you received this email, your email notifications are working correctly.

Team: 5454
Sent: 2025-10-11 03:20 PM UTC

==================================================
SAMPLE MATCH STRATEGY NOTIFICATION
==================================================

[Full match prediction output as shown above]
```

**Files Modified:**
- `app/routes/notifications.py` (lines 236-298)

---

### 4. ✅ Auto-Create Missing Database Tables
**Problem:** If databases were deleted, server would crash with:
```
Database error: (sqlite3.OperationalError) no such table: notification_subscription
```

**Solution:** Added comprehensive table creation on server startup:
- Main database tables (scouting.db)
- Misc database tables (misc.db) - notifications
- Users database tables (users.db)
- Pages database tables (pages.db)
- APIs database tables (apis.db)

**Startup Sequence:**
1. Check database health
2. Initialize if needed
3. **Auto-create all missing tables** (NEW)
4. Verify each database bind
5. Print status for each database

**Console Output:**
```
Starting FRC Scouting Platform...
Database is healthy and ready.
Checking for missing database tables...
✅ Main database tables verified/created
✅ Misc database (notifications) tables verified/created
✅ Users database tables verified/created
✅ Pages database tables verified/created
✅ APIs database tables verified/created
Database table verification complete!
```

**Error Handling:**
- Each database bind has individual try/except blocks
- Warnings logged but don't stop server startup
- Server remains functional even if optional databases fail

**Files Modified:**
- `run.py` (lines 70-115)

---

## Testing Checklist

### Service Worker
- [x] Navigate to `/sw.js` - should return JavaScript file
- [x] Check browser console - no service worker errors
- [x] Push notification registration should succeed
- [x] Browser shows "Allow notifications" prompt

### Email Predictions
- [x] Create notification subscription for a team
- [x] Trigger notification (or wait for scheduled time)
- [x] Email contains match analysis section
- [x] Email shows team-by-team breakdown
- [x] Email includes predicted winner
- [x] Email displays point differentials

### Test Email
- [x] Click "Test Email" button on notifications page
- [x] Receive email within 1 minute
- [x] Email contains sample match prediction
- [x] Prediction shows actual data from current event
- [x] All formatting is readable

### Auto-Create Tables
- [x] Delete `instance/misc.db`
- [x] Restart server
- [x] Check console - "✅ Misc database tables verified/created"
- [x] Navigate to `/notifications` - no database errors
- [x] Can create subscriptions without errors
- [x] All CRUD operations work normally

---

## Database Schema - Notifications

### notification_subscription
- `id` - Primary key
- `user_id` - Foreign key to users
- `scouting_team_number` - Team scope
- `notification_type` - 'match_strategy', 'match_reminder', etc.
- `target_team_number` - Team to watch
- `event_code` - Event code
- `email_enabled` - Boolean
- `push_enabled` - Boolean
- `minutes_before` - Notification timing (default: 20)
- `is_active` - Boolean
- `created_at` - Timestamp
- `updated_at` - Timestamp

### device_token
- `id` - Primary key
- `user_id` - Foreign key to users
- `endpoint` - Push endpoint URL
- `p256dh` - Encryption key
- `auth` - Auth secret
- `user_agent` - Browser info
- `is_active` - Boolean
- `failure_count` - Auto-cleanup after 10 failures
- `created_at` - Timestamp
- `last_used` - Timestamp

### notification_log
- `id` - Primary key
- `user_id` - Foreign key to users
- `subscription_id` - Foreign key to subscriptions
- `notification_type` - Type of notification
- `title` - Notification title
- `message` - Notification body
- `match_id` - Related match
- `team_number` - Related team
- `event_code` - Related event
- `email_sent` - Boolean
- `push_sent` - Boolean
- `sent_at` - Timestamp
- `error_message` - If failed

### notification_queue
- `id` - Primary key
- `subscription_id` - Foreign key
- `match_id` - Related match
- `scheduled_for` - When to send
- `status` - 'pending', 'sent', 'failed', 'cancelled'
- `attempts` - Retry count (max 3)
- `last_attempt` - Timestamp
- `error_message` - If failed
- `created_at` - Timestamp
- `updated_at` - Timestamp

---

## API Endpoints - Notifications

### GET `/notifications/`
Main notifications management page

### POST `/notifications/subscribe`
Create or update notification subscription
- `notification_type` - Type of notification
- `target_team_number` - Team to watch
- `event_code` - Event code (optional)
- `email_enabled` - true/false
- `push_enabled` - true/false
- `minutes_before` - Minutes before match (default: 20)

### POST `/notifications/unsubscribe/<id>`
Deactivate a subscription

### POST `/notifications/register-device`
Register device for push notifications
- `subscription` - Push subscription object from browser

### POST `/notifications/remove-device/<id>`
Remove a device token

### POST `/notifications/test-email`
Send test email with random match prediction

### POST `/notifications/test-push`
Send test push notification to all user devices

### POST `/notifications/test-subscription/<id>`
Test a specific subscription (send immediately)

---

## Configuration

### VAPID Keys
- Auto-generated on first run
- Stored in `instance/vapid_keys.json`
- Used for push notification authentication
- Keep secure - don't commit to Git

### Email Configuration
- Uses existing `instance/email_config.json`
- SMTP settings from game configuration
- Falls back to console output if not configured

### Game Configuration
- `current_event_code` - Required for match notifications
- FIRST API settings - For scheduled match times
- TBA API settings - For predicted match times

---

## Performance Considerations

### Background Worker
- Runs every 1 minute
- Checks for pending notifications
- Updates match times every 5-10 minutes
- Auto-cleans old data after 7 days

### Database Queries
- Indexed on `scheduled_time` for fast lookups
- Indexed on `user_id` for user queries
- Limits to active subscriptions only
- Batch processing for multiple matches

### Push Notifications
- Queued and batched by user
- Retry logic (3 attempts max)
- Auto-cleanup of failed devices
- Async sending to avoid blocking

---

## Troubleshooting

### Service Worker Won't Register
1. Check browser console for errors
2. Verify HTTPS or localhost (required for push)
3. Clear browser cache and reload
4. Check `/sw.js` returns valid JavaScript
5. Verify MIME type is `application/javascript`

### No Predictions in Emails
1. Ensure scouting data exists for teams
2. Check `ScoutingData` table has entries
3. Verify `auto_points` and `teleop_points` fields exist
4. Check console logs for calculation errors
5. Test with `/test-email` endpoint first

### Tables Not Created
1. Check console for "✅ tables verified/created" messages
2. Verify `instance` directory exists and is writable
3. Check for SQLAlchemy warnings in console
4. Manually run: `db.create_all(bind_key='misc')`
5. Check file permissions on instance folder

### Notifications Not Sending
1. Verify match has `scheduled_time` or `predicted_time`
2. Check notification worker is running (console logs)
3. Review `notification_queue` table status
4. Check `notification_log` for error messages
5. Verify email/push credentials are configured

---

## Future Enhancements

### Planned Features
- [ ] SMS notifications via Twilio
- [ ] Discord webhook integration
- [ ] Slack integration
- [ ] Custom notification templates
- [ ] User notification preferences page
- [ ] Notification history with filtering
- [ ] Bulk subscription management
- [ ] Team-wide notification policies
- [ ] Match outcome notifications (post-match)
- [ ] Alliance selection notifications

### Performance Improvements
- [ ] Redis queue for high-volume events
- [ ] Celery background tasks
- [ ] WebSocket push for instant updates
- [ ] Database connection pooling
- [ ] Notification batching by time window

---

## Files Modified Summary

1. **app/__init__.py**
   - Added proper MIME type to service worker route
   - Fixed path resolution for sw.js

2. **app/utils/notification_service.py**
   - Enhanced match prediction algorithm
   - Added team-by-team analysis
   - Calculated predicted scores and winners

3. **app/routes/notifications.py**
   - Added random match prediction to test emails
   - Improved error handling

4. **run.py**
   - Added auto-create tables on startup
   - Individual checks for each database bind
   - Graceful error handling for optional databases

---

## Support

For issues or questions:
1. Check console logs for error messages
2. Review `notification_log` table for delivery status
3. Test with simple subscriptions first
4. Verify API credentials are configured
5. Check this documentation for troubleshooting steps

---

**All fixes tested and verified - Ready for production! 🚀**
