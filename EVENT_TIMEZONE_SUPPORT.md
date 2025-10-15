# Event Timezone Support Documentation

## Overview

ObsidianScout now fully supports event-based timezones to ensure notifications and match times are displayed correctly regardless of where users are located around the world. This update addresses the issue where notifications were being sent based on UTC time instead of the event's local time.

## Problem Solved

**Previous Behavior:**
- All match times were stored and displayed in UTC
- Notifications were scheduled based on UTC time
- If an event was in Mountain Time and a match was at 9:00 AM MT, notifications would be sent based on the UTC equivalent (e.g., 3:00 PM UTC)
- This caused confusion for users in different timezones

**New Behavior:**
- Events store their IANA timezone (e.g., 'America/Denver' for Mountain Time)
- Match times are still stored in UTC (for database consistency)
- Match times are **displayed** in the event's local timezone
- Notifications are scheduled to arrive X minutes before the match starts **in local time**
- Works correctly for all timezones worldwide

## Example Scenario

**Event:** Silicon Valley Regional in California (Pacific Time - `America/Los_Angeles`)
**Match Time:** 2:30 PM Pacific Time
**User Location:** New York (Eastern Time)
**Notification Setting:** 20 minutes before match

### What Happens:
1. API provides match time: 2:30 PM PST
2. System converts to UTC: 10:30 PM UTC (stored in database)
3. System stores event timezone: `America/Los_Angeles`
4. Notification scheduled for: 10:10 PM UTC (20 minutes before 10:30 PM UTC)
5. User in New York sees match time displayed as: 5:30 PM EST (their local time)
6. User receives notification at: 5:10 PM EST (20 minutes before match in their local time)
7. User in California sees match time displayed as: 2:30 PM PST (event local time)
8. User in California receives notification at: 2:10 PM PST (20 minutes before match)

✅ **Result:** Everyone gets notified at the correct time relative to when the match actually starts!

## Technical Implementation

### 1. Database Schema Changes

**Event Model (`app/models.py`):**
```python
class Event(db.Model):
    # ... existing fields ...
    timezone = db.Column(db.String(50), nullable=True)  # IANA timezone like 'America/Denver'
```

### 2. API Integration

**TBA API (`app/utils/tba_api_utils.py`):**
- Captures `timezone` field from TBA event objects
- TBA provides IANA timezone strings

**FIRST API (`app/utils/match_time_fetcher.py`):**
- Parses ISO 8601 time strings
- Converts to UTC using event timezone for storage

### 3. Timezone Utilities (`app/utils/timezone_utils.py`)

New utility functions for timezone handling:

- `convert_local_to_utc(dt, event_timezone_str)` - Convert event local time to UTC
- `convert_utc_to_local(dt_utc, event_timezone_str)` - Convert UTC to event local time  
- `format_time_with_timezone(dt, event_timezone_str, format_str)` - Format time with timezone abbreviation
- `get_timezone_display_name(event_timezone_str)` - Get human-readable timezone name
- `parse_iso_with_timezone(iso_string, default_timezone_str)` - Parse ISO times with timezone support

### 4. Notification Scheduling (`app/utils/notification_service.py`)

**Key Changes:**
```python
# Match times are stored in UTC
match_time_utc = get_match_time(match)  # Returns UTC datetime

# Calculate notification send time
# Subtracting minutes from UTC time ensures notification arrives
# X minutes before match starts in LOCAL time
send_time = match_time_utc - timedelta(minutes=subscription.minutes_before)

# Schedule notification for that UTC time
# When that UTC time arrives, it will be X minutes before the match locally
```

### 5. Template Display (`app/utils/template_filters.py`)

New Jinja2 filters for templates:

```jinja2
{# Display match time in event timezone with abbreviation #}
{{ match.scheduled_time | format_time_tz(event.timezone) }}
{# Output: "2:30 PM PST" #}

{# Custom format with timezone #}
{{ match.scheduled_time | format_time_tz(event.timezone, '%Y-%m-%d %I:%M %p') }}
{# Output: "2024-03-15 2:30 PM PST" #}

{# Convert to local timezone (returns datetime object) #}
{% set local_time = match.scheduled_time | to_local_tz(event.timezone) %}
```

## Supported Timezones

ObsidianScout supports all IANA timezone strings, including:

**US Timezones:**
- `America/New_York` - Eastern Time
- `America/Chicago` - Central Time  
- `America/Denver` - Mountain Time
- `America/Phoenix` - Mountain Time (no DST)
- `America/Los_Angeles` - Pacific Time
- `America/Anchorage` - Alaska Time
- `Pacific/Honolulu` - Hawaii Time

**Canadian Timezones:**
- `America/Toronto` - Eastern Time
- `America/Winnipeg` - Central Time
- `America/Edmonton` - Mountain Time
- `America/Vancouver` - Pacific Time

**International:** All IANA timezones are supported (Australia, Europe, Asia, etc.)

## Migration Process

### Running the Migration

To add the timezone column and backfill data:

```bash
python -c "from app import create_app, db; from migrate_event_timezone import run_migration; app = create_app(); app.app_context().push(); run_migration()"
```

### What the Migration Does

1. **Adds Column:** Adds `timezone VARCHAR(50)` to the `event` table
2. **Backfills Data:** Fetches timezone info from TBA API for existing events
3. **Updates Metadata:** Also updates location, start_date, end_date if missing

### After Migration

- New events automatically get timezone from API
- Existing events will have timezone populated (if available from API)
- Events without timezone will default to UTC display

## API References

### The Blue Alliance API
- **Endpoint:** `GET /api/v3/event/{event_key}`
- **Timezone Field:** Returns `timezone` with IANA string
- **Documentation:** https://www.thebluealliance.com/apidocs/v3

### FIRST API  
- **Endpoint:** `GET /v2.0/{season}/schedule/{event_code}`
- **Time Format:** ISO 8601 with timezone offset
- **Documentation:** https://frc-api-docs.firstinspires.org/

## Usage Examples

### In Python Code

```python
from app.utils.timezone_utils import convert_utc_to_local, format_time_with_timezone
from app.models import Event, Match

# Get event and match
event = Event.query.filter_by(code='2024cala').first()
match = Match.query.filter_by(event_id=event.id, match_number=15).first()

# Convert match time to event local timezone
local_time = convert_utc_to_local(match.scheduled_time, event.timezone)
print(f"Match starts at: {local_time.strftime('%I:%M %p %Z')}")
# Output: "Match starts at: 02:30 PM PST"

# Format with timezone
formatted = format_time_with_timezone(match.scheduled_time, event.timezone)
print(formatted)
# Output: "02:30 PM PST"
```

### In Templates

```jinja2
{% if match.scheduled_time and event.timezone %}
  <p>Match Time: {{ match.scheduled_time | format_time_tz(event.timezone) }}</p>
  <p>Timezone: {{ event.timezone }}</p>
{% elif match.scheduled_time %}
  <p>Match Time: {{ match.scheduled_time.strftime('%I:%M %p') }} UTC</p>
{% else %}
  <p>Match time not scheduled yet</p>
{% endif %}
```

### Creating Notifications

```python
from app.models_misc import NotificationSubscription

# Create subscription for Team 5454
subscription = NotificationSubscription(
    user_id=current_user.id,
    scouting_team_number=5454,
    notification_type='match_strategy',
    target_team_number=5454,
    event_code='2024cala',
    minutes_before=20,  # Notify 20 minutes before match in LOCAL time
    email_enabled=True,
    push_enabled=True
)
db.session.add(subscription)
db.session.commit()
```

## Troubleshooting

### Events Missing Timezone

If an event doesn't have timezone information:

1. **Check API:** Verify TBA has timezone data for the event
2. **Manual Update:** Update directly in database:
   ```python
   from app import db
   from app.models import Event
   
   event = Event.query.filter_by(code='2024test').first()
   event.timezone = 'America/Chicago'
   db.session.commit()
   ```

3. **Re-sync:** Use the "Refresh Schedule" button in notifications page

### Notifications at Wrong Time

If notifications arrive at incorrect times:

1. **Check Event Timezone:** Verify event has correct timezone set
2. **Check Match Time:** Ensure match time is correctly stored in UTC
3. **Refresh Schedule:** Click "Refresh Schedule" to re-fetch times from API
4. **Check Logs:** Look for timezone conversion messages in notification worker logs

### Display Issues

If times display incorrectly in UI:

1. **Template Filters:** Ensure using `format_time_tz` filter with event.timezone
2. **Event Object:** Verify event object is passed to template
3. **Timezone Field:** Check event.timezone is not None

## Testing

### Test Timezone Conversion

```python
from app.utils.timezone_utils import *
from datetime import datetime, timezone

# Test conversion
dt_utc = datetime(2024, 3, 15, 22, 30, 0, tzinfo=timezone.utc)  # 10:30 PM UTC
dt_local = convert_utc_to_local(dt_utc, 'America/Los_Angeles')
print(dt_local.strftime('%I:%M %p %Z'))  # Should show 2:30 PM PST

# Test formatting
formatted = format_time_with_timezone(dt_utc, 'America/Denver')
print(formatted)  # Should show "03:30 PM MST"
```

### Test Notification Scheduling

1. Create a test event with timezone
2. Add matches with scheduled times
3. Create notification subscription
4. Monitor notification_worker.py logs for timezone messages
5. Verify notifications appear in queue with correct send times

## Best Practices

1. **Always Fetch Event Details:** When creating events, fetch full details from API to get timezone
2. **Store Times in UTC:** Always store match times in UTC in the database
3. **Convert for Display:** Convert to local timezone only when displaying to users
4. **Use Template Filters:** Use provided Jinja2 filters in templates for consistent formatting
5. **Handle Missing Timezone:** Always check if event.timezone exists before conversion
6. **Log Timezone Info:** Log timezone conversions in notification scheduling for debugging

## Future Enhancements

Potential improvements for future versions:

1. **User Timezone Preference:** Allow users to set their personal timezone for display
2. **Timezone Detection:** Auto-detect user's timezone from browser
3. **Multi-Event View:** Show times from multiple events in user's local timezone
4. **Calendar Export:** Generate .ics files with correct timezone information
5. **Timezone Editor:** Admin interface to manually set/update event timezones

## Summary

The timezone support ensures that ObsidianScout works correctly for FRC events happening anywhere in the world. Match times and notifications are now always accurate relative to the event's local time, regardless of where users are located. This makes the system truly international and eliminates confusion about when matches are actually happening.

**Key Points:**
- ✅ Match times stored in UTC (database standard)
- ✅ Event timezone stored separately (IANA format)
- ✅ Times displayed in event local timezone
- ✅ Notifications sent at correct local time
- ✅ Works for all timezones worldwide
- ✅ Automatic timezone from TBA API
- ✅ Backward compatible with existing data
