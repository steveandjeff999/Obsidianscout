# Schedule Adjustment Feature - Quick Start Guide

## What Was Implemented

The system now automatically detects when FRC events are running behind or ahead of schedule and adjusts match times and notifications accordingly.

## Key Features

### 1. **Automatic Schedule Detection**
- Every 15 minutes, the system checks completed matches
- Compares scheduled times vs actual times from The Blue Alliance API
- Calculates average delay/advance with confidence scoring

### 2. **Smart Adjustments**
- Adjusts future match predictions when events are delayed
- Only applies adjustments when confidence is high (>30%)
- Prioritizes recent matches for more accurate predictions

### 3. **Notification Rescheduling**
- Automatically reschedules pending notifications based on adjusted times
- Ensures users get notified at the correct time, not too early or too late

### 4. **Visual Indicators**
In the `/matches/` page, you'll now see:
- **Strikethrough original time** when schedule is adjusted
- **Bold adjusted time** in yellow/warning color
- **Badge showing delay amount** (e.g., "16m " for 16 minutes behind)
- **Alert color changes** from blue to yellow when schedule is off

## Example Display

### When event is on schedule:
```
02:30 PM
```

### When event is 16 minutes behind:
```
02:30 PM  (crossed out)
~02:46 PM  (in yellow/bold)  [16m ]
```

## How to Test

1. **Run the test script:**
   ```powershell
   .\.venv\Scripts\python.exe test_schedule_adjustment.py
   ```

2. **Check the console output** when the app is running:
   - Look for schedule adjustment checks every 15 minutes
   - See detected delays and adjusted match counts

3. **View matches page** at `/matches/`
   - Check if adjusted times are displayed
   - Look for delay badges

## Files Modified

### New Files:
- `app/utils/schedule_adjuster.py` - Core schedule adjustment logic
- `add_schedule_offset_column.py` - Database migration
- `test_schedule_adjustment.py` - Test script
- `DYNAMIC_SCHEDULE_ADJUSTMENT.md` - Full documentation

### Modified Files:
- `app/models.py` - Added `schedule_offset` field to Event model
- `app/utils/notification_worker.py` - Added schedule check every 15 minutes
- `app/utils/notification_service.py` - Updated to use adjusted times
- `app/utils/match_time_fetcher.py` - Better handling of actual times
- `app/templates/matches/index.html` - Shows adjusted times
- `app/templates/matches/view.html` - Shows adjusted times with details

## Configuration

The schedule adjuster will apply adjustments when:
- **Confidence ≥ 30%** (at least a few matches completed with consistent delays)
- **Offset ≥ 5 minutes** (significant enough to matter)

These thresholds can be adjusted in `app/utils/schedule_adjuster.py`.

## What Happens Automatically

Once running, the system will:
1.  Update match times from APIs every 10 minutes
2.  Check for schedule delays every 15 minutes
3.  Adjust future match predictions when delays detected
4.  Reschedule pending notifications automatically
5.  Display adjusted times in the UI
6.  Log schedule changes to console

## Troubleshooting

**Q: I don't see adjusted times**
- Event might be on schedule (good!)
- Not enough matches played yet
- Check console logs for schedule analysis results

**Q: Adjustments seem wrong**
- System requires multiple completed matches for accuracy
- Confidence builds as more matches are played
- Recent matches are weighted more heavily

**Q: Notifications still wrong time**
- Run the test script to verify system is working
- Check that matches have `scheduled_time` set
- Verify TBA API is returning actual times

## Next Steps

The system is now fully operational! It will:
- Monitor events automatically
- Adjust schedules as needed
- Keep notifications timely

No manual intervention needed - it just works! 
