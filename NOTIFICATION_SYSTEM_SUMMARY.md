# Notification System Implementation Summary

## 🎯 Overview
Implemented a comprehensive notification system for match strategy reminders with email and push notification support. Users can subscribe to notifications for specific teams and receive alerts 20 minutes (configurable) before their matches start.

## ✅ Completed Features

### 1. Database Models (`app/models_misc.py`)
Created in new **misc.db** database:
- **NotificationSubscription**: User subscriptions for match notifications
  - Per-team, per-event subscriptions
  - Configurable timing (minutes before match)
  - Email and push toggle options
  
- **DeviceToken**: Web push notification device registration
  - Stores push subscription endpoints and encryption keys
  - Tracks device status and success/failure counts
  - Auto-cleanup of inactive devices
  
- **NotificationLog**: Complete history of sent notifications
  - Tracks delivery success for both email and push
  - Stores error messages for debugging
  - Links to match and subscription context
  
- **NotificationQueue**: Pending notifications scheduler
  - Scheduled delivery times
  - Retry logic (up to 3 attempts)
  - Status tracking (pending/sent/failed/cancelled)

### 2. Match Time Tracking (`app/models.py`)
- Added `scheduled_time` field to Match model (indexed)
- Added `predicted_time` field for TBA predicted times
- Both fields populated from FIRST and TBA APIs

### 3. Notification Services

#### **Push Notifications** (`app/utils/push_notifications.py`)
- Web Push Protocol implementation using `pywebpush`
- VAPID key generation and storage
- Device registration and management
- Send to individual device or all user devices
- Automatic endpoint expiration handling

#### **Email Notifications** (uses existing `app/utils/emailer.py`)
- HTML-formatted emails with match details
- Uses SMTP configuration from `instance/email_config.json`
- Graceful fallback if email not configured

#### **Notification Scheduler** (`app/utils/notification_service.py`)
- Creates notification messages based on subscription type
- Schedules notifications X minutes before match
- Processes pending notification queue
- Automatic retry logic for failed deliveries
- Cleanup of old queue entries and logs

#### **Match Time Fetcher** (`app/utils/match_time_fetcher.py`)
- Fetches scheduled times from FIRST API (`/schedule` endpoints)
- Fetches predicted times from TBA API
- Updates all active events across all scouting teams
- Handles both APIs with automatic fallback

### 4. API Routes (`app/routes/notifications.py`)
Comprehensive REST API:
- `GET /notifications/` - Main management page
- `POST /notifications/subscribe` - Create/update subscription
- `POST /notifications/unsubscribe/<id>` - Remove subscription
- `POST /notifications/register-device` - Register push device
- `POST /notifications/remove-device/<id>` - Remove device
- `POST /notifications/test-email` - Send test email
- `POST /notifications/test-push` - Send test push
- `POST /notifications/test-subscription/<id>` - Test specific subscription
- `GET /notifications/vapid-public-key` - Get VAPID key for client
- `GET /notifications/history` - Get notification history

### 5. User Interface (`app/templates/notifications/index.html`)
Beautiful, comprehensive notification management page:
- **Push Notification Setup**: Enable/test browser notifications
- **Subscription Form**: Create subscriptions for specific teams
  - Team selector (populated from current event)
  - Notification type selection
  - Configurable timing (5-120 minutes before)
  - Email/push toggle checkboxes
- **Active Subscriptions List**: View and manage subscriptions
  - Test button for each subscription
  - Remove button for quick unsubscribe
- **Registered Devices**: View all registered devices
  - Device name and status indicator
  - Last success timestamp
  - Remove device option
- **Test Section**: Quick test buttons for email and push
- **Notification History**: View recent notifications sent
  - Delivery status badges
  - Email/push success indicators

### 6. Background Worker (`app/utils/notification_worker.py`)
Daemon thread that runs continuously:
- **Every 1 minute**: Process pending notifications
- **Every 5 minutes**: Schedule notifications for upcoming matches
- **Every 10 minutes**: Update match times from APIs
- **Every 1 hour**: Cleanup old data

### 7. Service Worker Enhancement (`sw.js`)
Added push notification handlers:
- `push` event: Display notifications
- `notificationclick` event: Navigate to match page
- `notificationclose` event: Cleanup
- Proper badge and icon support
- Vibration patterns

### 8. Integration
- **Added to `run.py`**: Notification worker thread started at startup
- **Registered blueprint**: Added to `app/__init__.py`
- **Navigation link**: Added to Community section in sidebar
- **Dependencies**: Added `pywebpush>=1.14.0` to requirements.txt
- **Database bind**: Added `misc` database to SQLALCHEMY_BINDS

## 🚀 How to Use

### For Users:

1. **Enable Push Notifications**
   - Go to `/notifications`
   - Click "Enable Push Notifications"
   - Allow browser permission when prompted

2. **Create Subscription**
   - Select a team from the dropdown
   - Choose notification type (Match Strategy recommended)
   - Set minutes before match (default 20)
   - Enable email and/or push
   - Click "Create Subscription"

3. **Test Notifications**
   - Use "Test Email" or "Test Push" buttons
   - Or test specific subscription with its test button

### For Administrators:

1. **Configure Email** (if not already done)
   - Email config stored in `instance/email_config.json`
   - Use existing email configuration UI

2. **Configure APIs**
   - FIRST API: Configure in game config (`current_event_code`)
   - TBA API: Configure in game config (`tba_api_settings`)
   - Match times auto-fetched every 10 minutes

3. **Monitor System**
   - Notification history visible to each user
   - Background worker logs to console
   - Check `instance/misc.db` for database status

## 📊 Technical Details

### Match Time Sources (Priority Order):
1. **FIRST API** (`/v2.0/{season}/schedule/{event_code}/qual|playoff|practice`)
   - Returns `startTime` field (ISO 8601 format)
   - Most reliable for official match times

2. **TBA API** (`/event/{event_key}/matches`)
   - Returns `actual_time` and `predicted_time` (Unix timestamps)
   - Good fallback and prediction data

### Notification Timing:
- Background worker checks every minute
- Notifications scheduled when match time - minutes_before <= current time
- 3 retry attempts for failed deliveries
- Queue entries auto-cleaned after 7 days

### Push Notification Security:
- VAPID keys auto-generated and stored in `instance/vapid_keys.json`
- Endpoint URLs unique per device
- Encryption keys (p256dh, auth) stored securely
- Dead endpoints auto-detected and marked inactive

### Database Isolation:
- Notifications use separate `misc.db` database
- No foreign key constraints to other databases (SQLite limitation)
- User IDs stored as integers with runtime lookups
- Prevents notification system from affecting core scouting data

## 🔧 Configuration Options

### Subscription Options:
- **notification_type**: 'match_strategy' or 'match_reminder'
- **minutes_before**: 5 to 120 minutes
- **email_enabled**: true/false
- **push_enabled**: true/false

### Worker Configuration (in `notification_worker.py`):
- Match time update interval: 600 seconds (10 min)
- Schedule check interval: 300 seconds (5 min)
- Notification processing: 60 seconds (1 min)
- Cleanup interval: 3600 seconds (1 hour)

### Queue Configuration:
- Max retry attempts: 3
- Queue retention: 7 days
- Device failure threshold: 10 (before auto-removal)

## 📝 Files Created/Modified

### Created:
- `app/models_misc.py` - Notification database models
- `app/utils/push_notifications.py` - Web push service
- `app/utils/notification_service.py` - Notification scheduler
- `app/utils/notification_worker.py` - Background worker
- `app/utils/match_time_fetcher.py` - API time fetcher
- `app/routes/notifications.py` - API routes
- `app/templates/notifications/index.html` - UI page

### Modified:
- `app/__init__.py` - Added misc database bind, registered blueprint
- `app/models.py` - Added scheduled_time and predicted_time to Match
- `run.py` - Added notification worker thread
- `sw.js` - Added push notification handlers
- `app/templates/base.html` - Added navigation link
- `requirements.txt` - Added pywebpush dependency

## 🧪 Testing Checklist

1. ✅ Create subscription for a team
2. ✅ Test email notification
3. ✅ Test push notification
4. ✅ Enable browser push notifications
5. ✅ Register device
6. ✅ Test subscription (sends real notification)
7. ✅ Check notification history
8. ✅ Remove subscription
9. ✅ Remove device
10. ✅ Verify background worker logs
11. ✅ Check match times populated from API
12. ✅ Verify notifications sent 20 min before match

## 🐛 Troubleshooting

### Push Notifications Not Working:
- Check browser supports notifications (Chrome, Firefox, Edge)
- Verify HTTPS is enabled (or localhost for testing)
- Check VAPID keys generated: `instance/vapid_keys.json`
- Review browser console for errors
- Ensure service worker registered: check DevTools > Application

### Emails Not Sending:
- Check email config: `instance/email_config.json`
- Verify user has email address set
- Check SMTP credentials valid
- Review notification history for error messages

### Match Times Not Updating:
- Verify event code configured in game config
- Check API keys valid (FIRST and/or TBA)
- Review console logs for API errors
- Manually test API endpoints

### Notifications Not Being Sent:
- Check notification queue: `SELECT * FROM notification_queue`
- Verify match has scheduled_time or predicted_time
- Check subscription is_active = true
- Review notification_log for errors
- Verify background worker is running

## 🚀 Next Steps / Future Enhancements

1. **Additional Notification Types**:
   - Alliance selection reminders
   - Team scouting progress alerts
   - Event day notifications

2. **Enhanced Filtering**:
   - Only specific match types (qual/playoff)
   - Only matches where my team is playing
   - Custom match time windows

3. **Mobile App Integration**:
   - Native push notifications
   - Background sync

4. **Analytics Dashboard**:
   - Notification delivery rates
   - User engagement metrics
   - Popular notification times

5. **Advanced Scheduling**:
   - Multiple notification times per match
   - Snooze functionality
   - Smart timing based on match delays

## ✨ Summary

The notification system is now fully operational and provides:
- ✅ Multi-channel notifications (email + push)
- ✅ Team-specific match reminders
- ✅ Automatic match time updates from APIs
- ✅ User device management
- ✅ Comprehensive testing tools
- ✅ Complete notification history
- ✅ Reliable background processing
- ✅ Graceful error handling
- ✅ Isolated database storage

Users can now receive timely match strategy reminders ensuring they never miss important matches!
