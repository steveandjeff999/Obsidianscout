# Redundant Match Sync Implementation

## Overview
Implemented redundant match fetching from FIRST API to ensure all matches are synchronized, including:
- **Scheduled matches** (not yet played)
- **Completed matches** (with scores)
- **Practice, Qualification, and Playoff matches**

## Changes Made

### 1. Enhanced FIRST API Match Fetching (`app/utils/api_utils.py`)

#### New Functions:
- `fetch_from_endpoint()`: Helper function to fetch data from a single API endpoint
- `merge_match_lists()`: Merges two match lists, removing duplicates based on match number and tournament level

#### Updated `get_matches()` Function:
Now fetches matches from multiple endpoints with redundancy:

**Priority 1 - Schedule Endpoints** (includes future matches):
```
/v2.0/{season}/schedule/{event_code}/qual
/v2.0/{season}/schedule/{event_code}/playoff
/v2.0/{season}/schedule/{event_code}/practice
```

**Priority 2 - Matches Endpoint** (completed matches with results):
```
/v2.0/{season}/matches/{event_code}
```

**Priority 3 - Fallback Endpoints**:
```
/v2.0/{season}/schedule/{event_code}
/v2.0/{season}/schedule/{event_code}?tournamentLevel=all
/v2.0/{season}/scores/{event_code}/all
/v2.0/{season}/scores/{event_code}/qual
```

#### Match Merging Strategy:
- Combines results from all successful endpoints
- Removes duplicates based on `tournamentLevel_matchNumber` key
- Prefers matches with more complete data (e.g., has teams array or scheduled time)
- Ensures no match is lost if different endpoints return different subsets

### 2. Enhanced Match Conversion (`api_to_db_match_conversion()`)

Now handles multiple API response formats:

**FIRST API /schedule Format:**
```json
{
  "matchNumber": 1,
  "tournamentLevel": "Qualification",
  "startTime": "2025-10-03T19:00:00",
  "teams": [
    {"teamNumber": 323, "station": "Red1", "surrogate": false},
    ...
  ]
}
```

**FIRST API /matches Format:**
```json
{
  "matchNumber": 1,
  "tournamentLevel": "Qualification",
  "scoreRedFinal": 150,
  "scoreBlueFinal": 120,
  "teams": [...]
}
```

**TBA API Format:**
```json
{
  "match_number": 1,
  "comp_level": "qm",
  "alliances": {
    "red": {"team_keys": ["frc254", ...], "score": 150},
    "blue": {"team_keys": ["frc971", ...], "score": 120}
  }
}
```

### 3. Enhanced TBA API Match Fetching (`app/utils/tba_api_utils.py`)

Updated `get_tba_event_matches()`:
- Added documentation that TBA API already includes both scheduled and completed matches
- Added logging to show count of scheduled vs completed matches
- TBA API `/event/{event_key}/matches` returns all matches regardless of play status

## Benefits

### 1. **Future Match Visibility**
- Matches that haven't been played yet are now synchronized
- Scouting teams can see the full schedule ahead of time
- Enables pre-match strategy planning

### 2. **Data Redundancy**
- Fetches from multiple endpoints to ensure no matches are missed
- If one endpoint is incomplete or down, others provide backup
- Merging logic ensures duplicate-free results

### 3. **Comprehensive Match Data**
- Scheduled matches include time information
- Completed matches include scores and results
- All match types covered (practice, qualification, playoff)

### 4. **API Compatibility**
- Works with both FIRST API and The Blue Alliance API
- Handles different response formats gracefully
- Backward compatible with existing code

## Example Response Format

From FIRST API `/schedule/{event_code}/qual`:
```json
{
  "Schedule": [
    {
      "description": "Qualification 1",
      "startTime": "2025-10-03T19:00:00",
      "matchNumber": 1,
      "field": "Primary",
      "tournamentLevel": "Qualification",
      "teams": [
        {"teamNumber": 323, "station": "Red1", "surrogate": false},
        {"teamNumber": 5454, "station": "Red2", "surrogate": false},
        {"teamNumber": 5045, "station": "Red3", "surrogate": false},
        {"teamNumber": 2357, "station": "Blue1", "surrogate": false},
        {"teamNumber": 6424, "station": "Blue2", "surrogate": false},
        {"teamNumber": 3937, "station": "Blue3", "surrogate": false}
      ]
    }
  ]
}
```

## Usage

The changes are transparent to existing code. All match syncing operations will automatically:
1. Fetch from schedule endpoints for upcoming matches
2. Fetch from matches endpoint for completed matches
3. Merge results to eliminate duplicates
4. Store all matches in the database

### Automatic Sync (Background Thread)
The existing 3-minute auto-sync in `run.py` will now fetch all matches:
```python
match_data_list = get_matches_dual_api(event_code)
# Now includes both scheduled and completed matches
```

### Manual Sync (UI Button)
The existing "Sync Matches" button will fetch complete match data:
```
/matches/sync_from_config
```

## Future Enhancements

### Recommended: Add Scheduled Time to Match Model
To fully utilize the `startTime` data from FIRST API:

```python
# Add to Match model in app/models.py
scheduled_time = db.Column(db.DateTime, nullable=True)
```

This would enable:
- Display of match start times in UI
- Sorting matches by scheduled time
- Countdown timers for upcoming matches
- Better match scheduling visualizations

### Migration Command:
```python
# migrations/versions/add_scheduled_time_to_match.py
def upgrade():
    op.add_column('match', sa.Column('scheduled_time', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('match', 'scheduled_time')
```

## Testing

To test the redundant match sync:

1. **Verify Multiple Endpoints Are Called:**
   ```
   Check console output for:
   "=== Fetching from /schedule endpoints (includes upcoming matches) ==="
   "=== Fetching from /matches endpoint (completed matches with results) ==="
   ```

2. **Verify Match Counts:**
   ```
   Console should show:
   "Found X matches from /v2.0/2025/schedule/{event_code}/qual"
   "Found Y matches from /v2.0/2025/matches/{event_code}"
   "=== Total unique matches retrieved: Z ==="
   ```

3. **Verify No Duplicates:**
   - Total unique count should be correct (not sum of all endpoints)
   - Each match number + type combination should appear once

4. **Verify Future Matches:**
   - Matches with no scores (red_score=None, blue_score=None) should be present
   - These are scheduled but not yet played

## API Documentation References

### FIRST API:
- Official Docs: https://frc-api-docs.firstinspires.org/
- Schedule Endpoints: `/v2.0/{season}/schedule/{eventCode}/{tournamentLevel}`
  - `tournamentLevel` can be: `qual`, `playoff`, `practice`
- Matches Endpoint: `/v2.0/{season}/matches/{eventCode}`

### The Blue Alliance API:
- Official Docs: https://www.thebluealliance.com/apidocs/v3
- Matches Endpoint: `/event/{event_key}/matches`
  - Returns all matches including scheduled (unplayed) matches
  - Unplayed matches have null scores or score of -1

## Notes

- The Match model does not currently have a `scheduled_time` field, so this information is not persisted
- The conversion function includes a comment noting where `startTime` data is available
- Merging prefers matches with more complete data (teams array, scheduled time, etc.)
- Empty results are returned as an empty list rather than raising an error (event may simply have no matches scheduled yet)
