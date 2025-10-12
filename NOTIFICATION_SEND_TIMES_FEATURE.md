# Notification Send Times Display - Feature Complete

## Summary
Added display of scheduled notification send times in the web UI so users can see when notifications will be sent.

## Changes Made

### 1. Added Scheduled Notifications Section

**New UI Section:**
- Shows upcoming notifications that are scheduled to send
- Displays the exact send time for each notification
- Shows match information (team, match number, match time)
- Shows notification status (pending, sent, failed)

**Location:** Between "Registered Devices" and "Test Notifications" sections

**Display Format:**
```
📅 Scheduled Notifications

Team 1234 - Match #15
Match Strategy Reminder
⏰ Will send: 2025-10-11 02:30 PM | 🏆 Match time: 02:50 PM | Status: pending
```

### 2. Enhanced Notification History

**Improvements:**
- Shows team number badge for each notification
- Displays actual send time with clock emoji (⏰)
- Shows delivery status (📧 Email, 📱 Push)
- Shows failed count if any pushes failed (⚠️ X failed)

**Display Format:**
```
📜 Notification History

Match #15 Strategy Update [Team 1234]
Team 1234: Match coming up in 20 minutes...
⏰ Sent: 2025-10-11 02:30 PM | 📧 Email | 📱 Push (2) | ⚠️ 1 failed
```

### 3. Backend Changes

**Route Updates (`app/routes/notifications.py`):**
- Added query to fetch pending notifications from `NotificationQueue`
- Joins with `NotificationSubscription` and `Match` tables
- Filters for pending status and future send times
- Orders by scheduled send time (earliest first)
- Passes `pending_notifications` to template

**Query Logic:**
```python
pending_notifications = db.session.query(
    NotificationQueue, NotificationSubscription, Match
).join(
    NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
).join(
    Match, NotificationQueue.match_id == Match.id
).filter(
    NotificationSubscription.user_id == current_user.id,
    NotificationQueue.status == 'pending',
    NotificationQueue.scheduled_for > datetime.utcnow()
).order_by(NotificationQueue.scheduled_for.asc()).limit(50).all()
```

### 4. Beta Badge Display

**Already Implemented:**
- "Beta" badge shown in header
- Warning message about beta status
- Indicates feature may change

### 5. Device Removal Enhancement

**Already Implemented:**
- Removes device from DOM immediately (no page reload)
- Shows success message
- Displays register button if no devices left
- Smooth fade-out animation

## Data Flow

### Notification Scheduling Process

1. **Worker Creates Queue Entry:**
   - Notification worker runs every 10 minutes
   - Fetches upcoming matches from FRC APIs (FIRST + TBA)
   - Creates `NotificationQueue` entries for active subscriptions
   - Sets `scheduled_for` = match_time - minutes_before

2. **Queue Entry Example:**
   ```python
   NotificationQueue(
       subscription_id=123,
       match_id=456,
       scheduled_for=datetime(2025, 10, 11, 14, 30),  # 2:30 PM
       status='pending'
   )
   ```

3. **Worker Sends Notification:**
   - Worker checks queue every minute
   - Finds entries where `scheduled_for <= now` and `status == 'pending'`
   - Sends notification (email + push)
   - Updates status to 'sent'
   - Creates `NotificationLog` entry

4. **UI Displays:**
   - **Before send:** Shows in "Scheduled Notifications" section
   - **After send:** Shows in "Notification History" section

## API Integration

### Match Time Sources

The notification system uses match times from:

1. **FIRST Inspires API** (Primary)
   - Endpoint: `https://frc-api.firstinspires.org/v3.0/{season}/schedule/{eventCode}`
   - Provides: `scheduledTime` for each match
   - Updates: Real-time during events

2. **The Blue Alliance** (Backup)
   - Endpoint: `https://www.thebluealliance.com/api/v3/event/{eventKey}/matches`
   - Provides: `time` (Unix timestamp) for each match
   - Updates: Near real-time during events

3. **Predicted Times** (Fallback)
   - If no API times available
   - Based on match cycle time and event schedule
   - Less accurate but better than nothing

### Notification Timing

**Formula:**
```
send_time = match_scheduled_time - minutes_before
```

**Example:**
- Match scheduled: 3:00 PM
- User preference: 20 minutes before
- Notification sends: 2:40 PM

## UI Components

### Scheduled Notifications Card

```html
<div class="notification-card">
    <h3>📅 Scheduled Notifications</h3>
    <div class="history-item" style="border-left-color: #17a2b8;">
        <strong>Team 1234 - Match #15</strong>
        <br>
        <small>Match Strategy Reminder</small>
        <br>
        <small class="text-muted">
            ⏰ Will send: 2025-10-11 02:30 PM
            | 🏆 Match time: 02:50 PM
            | Status: pending
        </small>
    </div>
</div>
```

### Notification History Card

```html
<div class="history-item email-sent push-sent">
    <strong>Match #15 Strategy Update</strong>
    <span class="badge badge-info">Team 1234</span>
    <br>
    <small>Team 1234: Match coming up...</small>
    <br>
    <small class="text-muted">
        ⏰ Sent: 2025-10-11 02:30 PM
        | 📧 Email
        | 📱 Push (2)
        | ⚠️ 1 failed
    </small>
</div>
```

## User Benefits

### Visibility
✅ See exactly when notifications will be sent
✅ Verify timing is correct before match
✅ Understand notification schedule

### Control
✅ Adjust timing if needed (edit subscription)
✅ Cancel notifications (remove subscription)
✅ Test before important matches

### Feedback
✅ Confirm notifications were sent
✅ See delivery status (email/push)
✅ Identify delivery issues

## Technical Details

### Database Schema

**NotificationQueue:**
- `id` - Primary key
- `subscription_id` - References NotificationSubscription
- `match_id` - References Match
- `scheduled_for` - DateTime when to send (indexed)
- `status` - 'pending', 'sent', 'failed', 'cancelled'
- `attempts` - Number of send attempts
- `created_at` - When queue entry created
- `updated_at` - Last modification time

**NotificationLog:**
- `id` - Primary key
- `user_id` - User who received notification
- `subscription_id` - Which subscription triggered it
- `match_id` - Which match it's about
- `team_number` - Team being tracked
- `sent_at` - When notification was sent (indexed)
- `email_sent` - Boolean
- `push_sent_count` - Number of devices
- `push_failed_count` - Number of failures

### Performance

**Query Optimization:**
- Indexed on `scheduled_for` for fast lookups
- Indexed on `status` for filtering
- Limit 50 results to prevent slowdown
- Joins only necessary tables

**Caching:**
- VAPID keys cached in memory
- Match data cached between worker runs
- Event teams cached per page load

## Testing Checklist

### Scheduled Notifications Display
- [ ] Create a subscription for upcoming match
- [ ] Verify it appears in "Scheduled Notifications"
- [ ] Check send time is correct (match_time - minutes_before)
- [ ] Verify match time is shown
- [ ] Check status badge shows "pending"

### Notification History Display
- [ ] Send a test notification
- [ ] Verify it appears in "Notification History"
- [ ] Check sent time is displayed
- [ ] Verify delivery badges show correctly
- [ ] Check team number badge appears

### Device Removal
- [ ] Remove a device
- [ ] Verify it disappears immediately (no reload)
- [ ] Check register button appears if no devices
- [ ] Re-register the same device
- [ ] Verify it appears in device list

### API Integration
- [ ] Check match times update from FIRST API
- [ ] Verify fallback to TBA if FIRST unavailable
- [ ] Test predicted times as last resort
- [ ] Confirm notifications send at correct time

## Files Modified

1. ✅ `app/routes/notifications.py`
   - Added pending notifications query
   - Passed to template

2. ✅ `app/templates/notifications/index.html`
   - Added "Scheduled Notifications" section
   - Enhanced "Notification History" display
   - Beta badge already present
   - Device removal already optimized

## Documentation

### For Users
- Scheduled Notifications section shows upcoming alerts
- Times are calculated from match schedule
- Can verify timing before matches
- History shows what was sent and when

### For Developers
- Query joins NotificationQueue, Subscription, Match
- Filters for pending and future
- Orders by scheduled_for ascending
- Template receives list of tuples (queue, subscription, match)

## Future Enhancements

Possible improvements:
- Countdown timer to next notification
- Time zone conversion for user preferences
- Edit scheduled notification time
- Bulk cancel scheduled notifications
- Export notification schedule
- Calendar integration (ICS file)
- SMS notification option
- Slack/Discord webhook support

## Status

✅ **Feature Complete**
- Scheduled notifications display: ✅
- Send time shown: ✅
- Match time shown: ✅
- Status badges: ✅
- Notification history enhanced: ✅
- Beta badge: ✅ (already present)
- Device removal optimized: ✅ (already present)

**Ready for testing and deployment!**
