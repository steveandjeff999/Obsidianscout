# Dynamic Schedule Adjustment Feature

## Overview

This feature automatically detects when FRC events are running behind or ahead of schedule and adjusts match time predictions and notification timing accordingly. This ensures that notifications are sent at the correct time, even when the event schedule changes during competition.

## Problem Statement

### Example Scenario
- **Scheduled**: Match 5 was supposed to start at 2:00 PM
- **Reality**: It's now 2:20 PM and the API shows match 5 was actually played at 2:16 PM
- **Issue**: The event is **16 minutes behind schedule**

Without schedule adjustment:
- Notifications for future matches would be sent based on the original schedule
- Users would get notified too early and miss matches
- Match time predictions would be inaccurate

With schedule adjustment:
- System detects the 16-minute delay
- All future match predictions are adjusted by +16 minutes
- Notifications are automatically rescheduled to send at the correct adjusted times
- Users get timely, accurate notifications

## How It Works

### 1. Schedule Analysis

The `schedule_adjuster.py` module periodically (every 15 minutes):

1. **Fetches completed match data** from The Blue Alliance (TBA) API
2. **Compares scheduled vs actual times** for each completed match
3. **Calculates average delay/advance** across all completed matches
4. **Prioritizes recent matches** (last 3 matches get more weight)
5. **Calculates confidence score** based on:
   - Sample size (more matches = higher confidence)
   - Consistency (less variance = higher confidence)

### 2. Schedule Adjustment

When confidence is sufficient (>30%) and offset is significant (>5 minutes):

1. **Updates future match predictions**: Adjusts `predicted_time` field for all unplayed matches
2. **Stores event offset**: Saves the offset value to `Event.schedule_offset` field
3. **Reschedules notifications**: Clears old pending notifications and creates new ones with adjusted times

### 3. Notification Timing

The `notification_service.py` now uses adjusted times:

```python
def get_match_time(match):
    # Priority order:
    # 1. Predicted time (adjusted by schedule_adjuster)
    # 2. Scheduled time (original from API)
    if match.predicted_time:
        return match.predicted_time  # Use adjusted prediction
    elif match.scheduled_time:
        return match.scheduled_time
    return None
```

## Architecture

### New Files

#### `app/utils/schedule_adjuster.py`
Core module for schedule adjustment logic:

- **`ScheduleAdjuster` class**: Handles schedule analysis and adjustment for a single event
  - `analyze_schedule_variance()`: Detects delays/advances
  - `adjust_future_match_times()`: Updates future match predictions
  - `should_reschedule_notifications()`: Determines if reschedule is needed

- **Utility functions**:
  - `update_event_schedule()`: Process a single event
  - `update_all_active_events_schedule()`: Process all active events

#### `add_schedule_offset_column.py`
Database migration script to add `schedule_offset` field to Event table.

### Modified Files

#### `app/models.py`
Added `schedule_offset` column to Event model:
```python
schedule_offset = db.Column(db.Integer, nullable=True)
# Stores offset in minutes: positive = behind, negative = ahead
```

#### `app/utils/notification_worker.py`
Integrated schedule adjustment into background worker:
- Checks for schedule changes every 15 minutes
- Automatically adjusts predictions and reschedules notifications
- Logs significant schedule changes

#### `app/utils/notification_service.py`
Updated `get_match_time()` to prioritize adjusted predictions:
- Uses `predicted_time` (adjusted) over `scheduled_time` (original)
- Ensures notifications are sent based on realistic match times

#### `app/utils/match_time_fetcher.py`
Enhanced TBA data handling:
- Better detection of actual vs scheduled times
- Preserves original scheduled times for comparison
- Uses actual times when matches are complete

## Usage

### Automatic Operation

The schedule adjuster runs automatically in the background:

1. **Every 15 minutes**, the notification worker:
   - Checks all active events for schedule variance
   - Updates match predictions if delays are detected
   - Reschedules notifications as needed

2. **When adjustments are made**:
   - Console logs show the detected offset
   - Match predictions are updated in the database
   - Pending notifications are rescheduled

### Manual Trigger

You can manually trigger schedule adjustment for an event:

```python
from app.utils.schedule_adjuster import update_event_schedule

# Update schedule for specific event
result = update_event_schedule(
    event_code='CALA',
    scouting_team_number=5454,
    reschedule_notifications=True
)

print(f"Offset: {result['analysis']['offset_minutes']:.1f} minutes")
print(f"Confidence: {result['analysis']['confidence']:.1%}")
print(f"Adjusted: {result['adjusted_matches']} matches")
print(f"Rescheduled: {result['rescheduled_notifications']} notifications")
```

### Monitoring

Check console output for schedule adjustment activity:

```
⏱️  Checking for schedule delays/advances...
============================================================
🏢 Processing team 5454, event CALA
============================================================
🔍 Fetching match times from TBA for CALA...
  Match 5: Scheduled 02:00 PM, Actual 02:16 PM, Delay: +16.0 min
  Match 6: Scheduled 02:10 PM, Actual 02:25 PM, Delay: +15.0 min
  Match 7: Scheduled 02:20 PM, Actual 02:35 PM, Delay: +15.0 min

📊 Schedule Analysis for CALA:
   Average offset: +15.3 minutes (behind schedule)
   Recent offset: +15.3 minutes (last 3 matches)
   Confidence: 60.0%
   Sample size: 3 completed matches
   Std deviation: 0.5 minutes

🔧 Adjusting 47 future matches by +15.3 minutes...
  Match 8: 02:30 PM → 02:45 PM
  Match 9: 02:40 PM → 02:55 PM
  ...
✅ Adjusted 47 future match predictions

📅 Rescheduling notifications due to schedule changes...
  Cleared 23 old pending notifications
✅ Rescheduled 23 notifications

⚠️  Event CALA is 15 min behind schedule
```

## Configuration

### Adjustment Thresholds

Edit `app/utils/schedule_adjuster.py` to modify thresholds:

```python
def adjust_future_match_times(self, min_confidence=0.3):
    # min_confidence: Minimum confidence (0-1) to apply adjustments
    # Default: 0.3 (30%)
    
def should_reschedule_notifications(self):
    # Reschedule if:
    # - Confidence >= 30%
    # - Offset >= 5 minutes
```

### Update Frequency

Edit `app/utils/notification_worker.py` to change check interval:

```python
# Check for schedule adjustments every 15 minutes (900 seconds)
if (now - last_schedule_adjustment).total_seconds() >= 900:
    # Change 900 to desired interval in seconds
```

## Database Schema

### Event Table
```sql
-- New column added to event table
ALTER TABLE event ADD COLUMN schedule_offset INTEGER;

-- Values:
-- NULL = No adjustment calculated yet
-- 0 = Event is on schedule
-- Positive = Event is behind schedule (e.g., 15 = 15 minutes behind)
-- Negative = Event is ahead of schedule (e.g., -10 = 10 minutes ahead)
```

### Match Table
```sql
-- Existing columns used for adjustment:
-- scheduled_time: Original scheduled time from API (UTC)
-- predicted_time: Adjusted time based on schedule offset (UTC)
```

## API Integration

The schedule adjuster uses The Blue Alliance (TBA) API:

### Endpoints Used
- `GET /event/{event_key}/matches`: Fetches match details including:
  - `time`: Original scheduled time (Unix timestamp)
  - `actual_time`: When match actually played (Unix timestamp)
  - `predicted_time`: TBA's prediction (Unix timestamp)

### Data Flow
1. Fetch match data from TBA
2. Compare `time` vs `actual_time` for completed matches
3. Calculate average delay/advance
4. Apply offset to future matches
5. Update `predicted_time` in database

## Benefits

### For Users
- ✅ **Timely notifications**: No more missed matches due to schedule delays
- ✅ **Accurate predictions**: See realistic match times, not outdated schedules
- ✅ **Automatic updates**: No manual intervention needed

### For System
- ✅ **Smart adaptation**: Adjusts to real-world conditions automatically
- ✅ **Confidence-based**: Only applies adjustments when sufficiently confident
- ✅ **Recent data priority**: Weights recent matches more heavily
- ✅ **Graceful degradation**: Falls back to original schedule if no data available

## Example Scenarios

### Scenario 1: Event Running Behind
```
Matches 1-5 are delayed by 10-15 minutes each
→ System detects 12.5 minute average delay
→ Adjusts matches 6-50 by +12.5 minutes
→ Reschedules 25 pending notifications
→ Users receive notifications at correct adjusted times
```

### Scenario 2: Event Running Ahead
```
Matches 1-3 finish 5-8 minutes early
→ System detects 6.3 minute advance
→ Adjusts matches 4-40 by -6.3 minutes
→ Reschedules notifications earlier
→ Users get notified earlier to match actual pace
```

### Scenario 3: Event Back on Schedule
```
Event started late but caught up after lunch break
→ Early matches show +20 minute delay
→ Recent matches show +2 minute delay
→ System uses recent offset (weights last 3 matches)
→ Minimal adjustment applied
→ Confidence gradually decreases as variance increases
```

### Scenario 4: Insufficient Data
```
Only 1-2 matches completed
→ Confidence < 30%
→ No adjustment applied
→ System waits for more data
→ Falls back to original scheduled times
```

## Troubleshooting

### Notifications Still Incorrect

**Check 1**: Verify schedule adjustment is running
```python
# Look for these logs in console:
⏱️  Checking for schedule delays/advances...
```

**Check 2**: Check confidence level
```python
# If confidence < 30%, adjustments won't be applied
📊 Schedule Analysis for CALA:
   Confidence: 20.0%  # Too low!
```

**Check 3**: Verify event timezone is set
```python
from app.models import Event
event = Event.query.filter_by(code='CALA').first()
print(event.timezone)  # Should be like 'America/Los_Angeles'
```

### Schedule Offset Not Updating

**Check 1**: Ensure matches have actual times
```python
# TBA only provides actual_time after match is played
# Check TBA API response for actual_time field
```

**Check 2**: Verify TBA API access
```python
# Check for TBA API errors in logs:
⚠️  Could not fetch match details from TBA: 401
```

**Check 3**: Check match time updates
```python
# Match times should be updating every 10 minutes:
📅 Updating match times from APIs...
✅ Updated X match times
```

## Migration Instructions

### 1. Run Migration
```bash
python add_schedule_offset_column.py
```

### 2. Restart Application
The notification worker will automatically start checking for schedule adjustments.

### 3. Verify Operation
Check logs for schedule adjustment activity after 15 minutes.

## Future Enhancements

Possible improvements:

1. **User notifications**: Alert users when schedule changes significantly
2. **Historical tracking**: Store schedule offset history over time
3. **Predictive modeling**: Use ML to predict future delays based on patterns
4. **Event type factors**: Weight delays differently for quals vs playoffs
5. **UI dashboard**: Show current schedule status in web interface
6. **Manual override**: Allow admins to manually set schedule offset
7. **API endpoint**: Expose schedule status via REST API

## Technical Notes

### Thread Safety
- Schedule adjustment runs in notification worker thread
- Uses Flask app context for database access
- Database commits are atomic

### Performance
- Schedule analysis: ~2-5 seconds per event
- Database updates: Batch committed for efficiency
- No impact on notification processing

### Timezone Handling
- All times stored in UTC in database
- Conversions to local time for display only
- Schedule offset calculations done in UTC to avoid DST issues

## Credits

Developed to solve the real-world problem of FRC events running behind schedule, causing missed notifications and user frustration. The system intelligently adapts to actual event pace while maintaining high confidence thresholds to avoid false adjustments.

## Mobile API: Scheduled Notifications

The system exposes pending scheduled notifications to mobile clients via a dedicated mobile API endpoint. This allows mobile apps to display upcoming reminders and the delivery methods configured for each subscription.

- **Endpoint:** `GET /api/mobile/notifications/scheduled`
- **Scope:** Results are scoped to the authenticated scouting team (token `team_number`).
- **Delivery methods:** The response includes `delivery_methods` with `email` and `push` booleans indicating which channels are enabled on the subscription.
- **Weather:** The `weather` field is returned as `null` by default. Server-side weather integration is optional; mobile apps may perform their own weather lookups for scheduled times/locations if needed.

This mobile exposure makes it easy for client apps to show upcoming notifications (and whether they will be delivered via email, push, or both) and to surface any schedule-adjusted times to users.
