# Timezone Support Implementation Summary

## ✅ Completed Changes

### 1. **Database Schema**
- Added `timezone` column to `Event` model to store IANA timezone strings (e.g., 'America/Denver')
- Updated Match model documentation to clarify times are stored in UTC

### 2. **API Integration**

#### TBA API (The Blue Alliance)
- Updated `tba_event_to_db_format()` to capture timezone field from TBA events
- TBA provides accurate IANA timezone strings for all events

#### FIRST API
- Updated `get_event_details()` to return standardized format with timezone
- FIRST API doesn't provide timezone directly, so it falls back to TBA for timezone data
- Converts FIRST API dates and times properly
- Returns database-compatible format for event creation

### 3. **Timezone Utilities** (`app/utils/timezone_utils.py`)
Created comprehensive timezone handling functions:
- `convert_local_to_utc()` - Convert event local time to UTC for storage
- `convert_utc_to_local()` - Convert UTC to event local time for display
- `format_time_with_timezone()` - Format datetime with timezone abbreviation
- `get_timezone_display_name()` - Human-readable timezone names
- `parse_iso_with_timezone()` - Parse ISO 8601 times with timezone support
- `get_current_time_in_timezone()` - Get current time in event timezone

### 4. **Match Time Fetching** (`app/utils/match_time_fetcher.py`)
- Updated `fetch_match_times_from_first()` to use event timezone for parsing
- Updated `fetch_match_times_from_tba()` to properly handle Unix timestamps as UTC
- Modified `update_match_times()` to fetch event timezone and pass to parsers
- All times are properly converted to UTC for database storage

### 5. **Notification System** (`app/utils/notification_service.py`)
- Updated notification scheduling to respect event timezones
- Notifications are sent X minutes before match starts in LOCAL time
- Added timezone logging for debugging
- Email notifications show match time in event local timezone

### 6. **Template Filters** (`app/utils/template_filters.py`)
Added Jinja2 filters for easy timezone display in templates:
```jinja2
{{ match.scheduled_time | format_time_tz(event.timezone) }}
{{ match.scheduled_time | format_time_tz(event.timezone, '%Y-%m-%d %I:%M %p') }}
{{ match.scheduled_time | to_local_tz(event.timezone) }}
```

### 7. **Event Sync**
- Updated `run.py` event creation to fetch full event details including timezone
- Updated `matches.py` sync to fetch timezone when creating events
- Events now automatically populate timezone from API

### 8. **UI Updates**

#### Matches Index Page (`/matches`)
- Added "Scheduled Time" column showing match times in event local timezone
- Shows timezone abbreviation (PST, EST, MST, etc.)
- Displays predicted time if scheduled time not available
- Falls back to UTC if event has no timezone

#### Match View Page (`/matches/view/<id>`)
- Added prominent alert box showing match schedule
- Displays full formatted time with timezone
- Shows both timezone name and IANA identifier
- Works for scheduled and predicted times

### 9. **Migration Script** (`migrate_event_timezone.py`)
- Adds timezone column to database
- Backfills timezone data from TBA API for existing events
- Safe to run multiple times
- Updates other missing event fields (location, dates)

### 10. **Documentation** (`EVENT_TIMEZONE_SUPPORT.md`)
- Comprehensive guide on timezone support
- Examples for developers
- Troubleshooting guide
- API references

## How It Works

### Example: Silicon Valley Regional (Pacific Time)

1. **Event Fetch**: TBA API provides timezone as `America/Los_Angeles`
2. **Match Time**: API says match at 2:30 PM PST
3. **Storage**: Converted to UTC (10:30 PM UTC) and stored in database
4. **Display**: 
   - User in California sees: **2:30 PM PST**
   - User in New York sees: **5:30 PM EST** (auto-converted by browser if we add that)
   - Current implementation shows event local time: **2:30 PM PST** (consistent for everyone)
5. **Notifications**: 
   - Set for 20 minutes before = 10:10 PM UTC
   - Arrives 20 minutes before 2:30 PM local time
   - Works correctly worldwide

## Usage

### In Templates
```html
<!-- Show match time in event timezone -->
{% if match.scheduled_time and event.timezone %}
    {{ match.scheduled_time | format_time_tz(event.timezone) }}
{% else %}
    {{ match.scheduled_time.strftime('%I:%M %p') }} UTC
{% endif %}

<!-- Show timezone name -->
{% if event.timezone %}
    <small>{{ event.timezone.split('/')[-1].replace('_', ' ') }}</small>
{% endif %}
```

### In Python Code
```python
from app.utils.timezone_utils import convert_utc_to_local, format_time_with_timezone

# Convert to local time
local_time = convert_utc_to_local(match.scheduled_time, event.timezone)

# Format with timezone
formatted = format_time_with_timezone(match.scheduled_time, event.timezone)
```

## Running the Migration

```bash
# From the project directory
python -c "from app import create_app, db; from migrate_event_timezone import run_migration; app = create_app(); app.app_context().push(); run_migration()"
```

## Testing

1. Start the app: `python run.py`
2. Navigate to `/matches`
3. Verify times show in event timezone
4. Click on a match to see detailed timezone info
5. Create notification subscriptions to test scheduling

## What's Different from Before

### Before:
- ❌ All times displayed in UTC
- ❌ Notifications sent based on UTC time
- ❌ Confusing for users in different timezones
- ❌ No timezone information stored

### After:
- ✅ Times displayed in event local timezone
- ✅ Notifications sent at correct local time
- ✅ Clear timezone indicators (PST, EST, etc.)
- ✅ Timezone stored and managed properly
- ✅ Works for all timezones worldwide
- ✅ FIRST API fallback to TBA for timezone data

## Benefits

1. **Accuracy**: Notifications arrive when they should relative to match time
2. **Clarity**: Users see times in the event's timezone, not UTC
3. **Global**: Works for events anywhere in the world
4. **Reliable**: Multiple API sources with fallback
5. **Automatic**: Timezone populated from APIs automatically
6. **Backward Compatible**: Existing data works (shows UTC if no timezone)

## Next Steps (Optional Future Enhancements)

1. Allow users to set personal timezone preference
2. Auto-detect user timezone from browser
3. Show match time in both event and user timezone
4. Export calendar files with proper timezone
5. Add timezone editor for admins

---

**Implementation Date**: October 15, 2025
**Status**: ✅ Complete and Ready for Testing
