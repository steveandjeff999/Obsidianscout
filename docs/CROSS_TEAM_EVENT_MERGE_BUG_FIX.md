# Cross-Team Event Merge Bug Fix

## Issue Summary

When editing a team's `game_config.json` file directly on the server with a lowercase event code, the auto-sync worker would trigger `merge_duplicate_events()` which incorrectly merged events across different scouting teams. This resulted in matches from one team appearing in another team's event, breaking team isolation.

## Root Cause

The `merge_duplicate_events()` function in `app/routes/data.py` was querying **ALL events regardless of scouting_team_number** and merging them if they had the same event code. This violated the fundamental team isolation principle where each scouting team should have completely separate data.

### Problematic Code (Before Fix)

```python
def merge_duplicate_events(scouting_team_number=None):
    """Merge duplicate events that have the same code, name, or year."""
    try:
        # Query ALL events regardless of scouting team to find cross-team duplicates
        all_events = Event.query.all()  # ❌ BUG: No scouting_team_number filter
        
        # ... merge logic that moves matches between events ...
```

## The Bug in Action

1. User edits Team 0's config file directly: `"current_event_code": "okok"` (lowercase)
2. Auto-sync worker for Team 0 runs:
   - Loads config with lowercase "okok"
   - Uses case-insensitive lookup to find/create Event with code "OKOK" for Team 0
   - Creates Event ID 3 with `scouting_team_number=0`
3. Auto-sync calls `merge_duplicate_events(scouting_team_number=0)`
4. **BUG TRIGGERS**: Function finds BOTH:
   - Event ID 3: code="OKOK", scouting_team=0, 110 matches
   - Event ID 8: code="OKOK", scouting_team=5454, 144 matches
5. Function merges them, moving ALL matches to one event
6. Team 5454's 144 matches now appear in Team 0's event (or vice versa)
7. Team isolation is broken!

## The Fix

Modified `merge_duplicate_events()` to only query events for the current scouting team:

```python
def merge_duplicate_events(scouting_team_number=None):
    """Merge duplicate events that have the same code, name, or year.
    
    This function finds and merges duplicate events by:
    1. Finding events with the same code (normalized) - ONLY within the same scouting team
    ...
    """
    try:
        # Query events ONLY for the current scouting team to avoid cross-team contamination
        if scouting_team_number is not None:
            all_events = Event.query.filter_by(scouting_team_number=scouting_team_number).all()
        else:
            all_events = Event.query.filter_by(scouting_team_number=None).all()
```

## Data Cleanup

Created two cleanup scripts:

### 1. `scripts/fix_cross_team_event_merge.py`

Fixes the corrupted data by:
- Finding events with the same code but different scouting_team_number
- Moving matches back to the correct team's event based on `match.scouting_team_number`
- Verifying team isolation is restored

**Results:**
- Moved 224 matches from Team 0's event back to Team 5454's event
- Final state: Team 0 has 95 matches, Team 5454 has 353 matches

### 2. `scripts/remove_duplicate_matches.py`

Removes duplicate matches created during the merge process:
- Groups matches by (event_id, match_number, match_type)
- Keeps the oldest match (lowest ID with scheduled time if available)
- Deletes duplicates

**Results:**
- Removed 224 duplicate matches
- Final state: Team 0 has 95 matches, Team 5454 has 144 matches (both correct)

## Final Verification

After fixes:
```
Event ID 3: code='OKOK', team=0
  Total matches: 95
  Correct team matches: 95
  Status: CORRECT

Event ID 8: code='OKOK', team=5454
  Total matches: 144
  Correct team matches: 144
  Status: CORRECT
```

## Additional Fixes

1. Updated Team 0's config file to uppercase: `"current_event_code": "OKOK"`
2. This prevents the bug from triggering again on next auto-sync

## Prevention

The fix ensures that:
1. ✅ Each scouting team's events are completely isolated
2. ✅ Event code normalization (uppercase) is consistent
3. ✅ `merge_duplicate_events()` only operates within a single team's scope
4. ✅ Case-insensitive event lookups include both code AND scouting_team_number filters

## Files Modified

- `app/routes/data.py` - Fixed `merge_duplicate_events()` function
- `instance/configs/0/game_config.json` - Uppercased event code
- `scripts/fix_cross_team_event_merge.py` - NEW: Data cleanup script
- `scripts/remove_duplicate_matches.py` - EXISTING: Used for deduplication

## Testing Recommendations

1. Test event creation with mixed-case event codes
2. Verify auto-sync doesn't create cross-team contamination
3. Test direct JSON config edits don't trigger merges
4. Verify team isolation holds when multiple teams use same event code

## Related Issues

This fix also addresses:
- Event code case sensitivity issues
- Duplicate match creation from repeated syncs
- Team isolation verification

## Date Fixed

January 2025
