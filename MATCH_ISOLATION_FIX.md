# Match Team Isolation Fix

## Problem
The matches page and dashboard were showing duplicate matches - each match was appearing multiple times (5x in the user's case), showing matches from ALL scouting teams instead of filtering to only the current user's scouting team.

## Root Cause Analysis

1. **Match Model Design**: The `Match` model has a `scouting_team_number` field, meaning each scouting team maintains their own copy of match data.

2. **Sync Process**: When matches are synced from the API (FIRST or TBA), the code correctly:
   - Filters existing matches by scouting team
   - Assigns scouting_team_number when creating NEW matches
   - BUT did NOT reassign scouting_team_number when UPDATING existing matches

3. **Display Queries**: The filtering functions were in place but:
   - Might have had issues with NULL scouting_team_number values
   - Lacked defensive checks to ensure isolation
   - Could have had issues if `get_current_scouting_team_number()` returned unexpected values

## Fixes Applied

### 1. Match Sync (app/routes/matches.py)
**Location**: `sync_from_config()` function, line ~331-347

**Change**: Ensured that `assign_scouting_team_to_model()` is called for BOTH new and existing matches:

```python
if match:
    # Update existing match
    match.red_alliance = match_data.get('red_alliance', match.red_alliance)
    match.blue_alliance = match_data.get('blue_alliance', match.blue_alliance)
    match.winner = match_data.get('winner', match.winner)
    match.red_score = match_data.get('red_score', match.red_score)
    match.blue_score = match_data.get('blue_score', match.blue_score)
    # Ensure scouting_team_number is set (in case it was None before)
    assign_scouting_team_to_model(match)  # ← ADDED THIS LINE
    matches_updated += 1
```

### 2. Matches Index Page (app/routes/matches.py)
**Location**: `index()` function, line ~69

**Change**: Added defensive filtering to explicitly check scouting_team_number:

```python
# Build base query for this event (filtered by scouting team)
query = filter_matches_by_scouting_team().filter(Match.event_id == event.id)

# Defensive check: ensure we only show matches for current scouting team
from app.utils.team_isolation import get_current_scouting_team_number
current_scouting_team = get_current_scouting_team_number()
if current_scouting_team is not None:
    query = query.filter(Match.scouting_team_number == current_scouting_team)
else:
    query = query.filter(Match.scouting_team_number.is_(None))
```

### 3. Dashboard (app/routes/main.py)
**Location**: `index()` function, line ~90

**Change**: Added the same defensive filtering for dashboard match queries:

```python
if current_event:
    matches_query = filter_matches_by_scouting_team().filter(Match.event_id == current_event.id)
    # Defensive check: ensure we only show matches for current scouting team
    from app.utils.team_isolation import get_current_scouting_team_number
    current_scouting_team = get_current_scouting_team_number()
    if current_scouting_team is not None:
        matches_query = matches_query.filter(Match.scouting_team_number == current_scouting_team)
    else:
        matches_query = matches_query.filter(Match.scouting_team_number.is_(None))
    matches = matches_query.order_by(Match.match_type, Match.match_number).all()
```

### 4. Matches Data API (app/routes/matches.py)
**Location**: `matches_data()` function, line ~1496

**Change**: Added defensive filtering for AJAX endpoints:

```python
matches_query = filter_matches_by_scouting_team().filter_by(event_id=current_event.id)
# Defensive check: ensure we only show matches for current scouting team
from app.utils.team_isolation import get_current_scouting_team_number
current_scouting_team = get_current_scouting_team_number()
if current_scouting_team is not None:
    matches_query = matches_query.filter(Match.scouting_team_number == current_scouting_team)
else:
    matches_query = matches_query.filter(Match.scouting_team_number.is_(None))
matches = matches_query.order_by(Match.match_number).all()
```

## Cleanup Tool

Created `cleanup/fix_match_team_isolation.py` to help clean up existing duplicate matches in the database.

**Usage**:
```bash
python cleanup/fix_match_team_isolation.py
```

**Features**:
- Analyzes the database for duplicate matches
- Shows which scouting teams have copies of each match
- Provides options to:
  1. Keep only matches for a specific scouting team
  2. Assign NULL matches to a specific scouting team
  3. Delete all NULL matches
  4. Exit without changes

## Testing Steps

1. **Run the cleanup tool**:
   ```bash
   cd "C:\Users\steve\OneDrive\Scout2026stuff\Release\OBSIDIAN-Scout Current\Obsidian-Scout"
   python cleanup/fix_match_team_isolation.py
   ```
   - Choose option 1 and enter your scouting team number to keep only your team's matches
   - Or use option 2 to assign NULL matches to your team

2. **Restart the application**:
   ```bash
   python run.py
   ```

3. **Verify the fixes**:
   - Navigate to the Matches page
   - Check that each match appears only once
   - Navigate to the Dashboard
   - Verify matches are not duplicated
   - Try syncing matches again and confirm no new duplicates appear

4. **Test with multiple scouting teams** (if applicable):
   - Log in as users from different scouting teams
   - Verify each team sees only their own matches
   - Sync matches from different accounts
   - Confirm isolation is maintained

## Prevention

The code changes ensure that:
1. All new match syncs properly assign scouting_team_number
2. Updates to existing matches maintain scouting_team_number
3. All display queries have defensive checks to filter by scouting_team_number
4. NULL scouting_team_number values are handled consistently

## Notes

- The defensive checks are redundant with `filter_matches_by_scouting_team()` but provide extra safety
- If you see duplicates after these fixes, check that:
  - Users have `scouting_team_number` properly set in their user accounts
  - The cleanup tool was run to remove existing duplicates
  - The application was restarted after code changes

## Files Modified

1. `app/routes/matches.py` - 3 changes
   - `sync_from_config()` - Added scouting team assignment on update
   - `index()` - Added defensive filtering
   - `matches_data()` - Added defensive filtering

2. `app/routes/main.py` - 1 change
   - `index()` (dashboard) - Added defensive filtering

3. `cleanup/fix_match_team_isolation.py` - New file
   - Database cleanup utility
