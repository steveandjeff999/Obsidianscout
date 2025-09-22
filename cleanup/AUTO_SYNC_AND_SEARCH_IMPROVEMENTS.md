# Auto-Sync and Search Improvements

## Changes Made

### 1. Auto-Sync API Data Every 3 Minutes

Added automatic synchronization of teams and matches data from the API every 3 minutes to keep the database up to date with the latest information.

#### Implementation Details:
- **File Modified**: `run.py`
- **New Feature**: Added `api_data_sync_worker()` background thread
- **Sync Interval**: 3 minutes (180 seconds)
- **What it syncs**: 
  - Teams data (team numbers, names, locations)
  - Matches data (schedules, alliances, scores)
- **Behavior**:
  - Only syncs data for the current event (from game_config.json)
  - Updates existing records if they already exist
  - Adds new records if they don't exist
  - Associates teams with events automatically
  - Handles errors gracefully and continues running

#### How it works:
1. Every 3 minutes, the background thread wakes up
2. Gets the current event code from configuration
3. Calls the dual API (FIRST API or TBA API) to fetch latest data
4. Compares with existing database records
5. Updates/adds records as needed
6. Commits changes to database
7. Logs activity to console

#### Benefits:
- Always have the latest team and match information
- Automatic updates without manual intervention
- Works with both FIRST API and The Blue Alliance API
- Respects team isolation (only syncs for your scouting team)

### 2. Fixed Team Search Issue

Fixed the search functionality so that searching for "5454" returns the same results as searching for "Team 5454".

#### Problem:
- Searching for just the team number (e.g., "5454") didn't return results
- Only searching for "Team 5454" would work
- This was due to improper handling of numeric vs. text searches

#### Solution:
- **Files Modified**: 
  - `app/routes/search.py`
  - `app/routes/auth.py`
- **Improvements**:
  - Added proper numeric team number searching
  - Uses `func.cast()` to convert team numbers to strings for partial matching
  - Handles both exact matches and partial matches
  - Improved relevance scoring for search results

#### Changes Made:

**In `search.py`:**
- Enhanced `search_teams()` function to handle numeric searches
- Added exact team number matching for highest relevance
- Added string casting for partial team number matches
- Improved relevance scoring system
- Updated API suggestions to handle numeric searches

**In `auth.py`:**
- Fixed user management search to handle team number searches properly
- Added numeric vs. text search detection
- Uses proper SQLAlchemy functions for type casting

#### How it works now:
1. **Numeric Search** (e.g., "5454"):
   - First tries exact team number match (highest relevance)
   - Then tries partial team number matches
   - Also searches in team names and locations
2. **Text Search** (e.g., "Team 5454", "Islanders"):
   - Searches in team names, locations, and team numbers
   - Proper relevance scoring based on match type

#### Benefits:
- More intuitive search behavior
- Both "5454" and "Team 5454" return results
- Better search relevance and ranking
- Consistent search behavior across all search interfaces

## New API Endpoint

### `/api/sync-status`
Added a new API endpoint to monitor sync status and statistics.

**Returns:**
```json
{
  "current_event_code": "2024cala",
  "current_event_name": "Los Angeles Regional",
  "api_sync_enabled": true,
  "statistics": {
    "total_teams": 45,
    "total_matches": 120,
    "total_events": 3,
    "current_event_teams": 45,
    "current_event_matches": 120,
    "recent_teams_added": 2,
    "recent_matches_added": 5
  },
  "sync_info": {
    "alliance_sync_interval": "30 seconds",
    "api_sync_interval": "3 minutes",
    "last_check": "2025-01-07T10:30:00.000Z"
  }
}
```

## Testing

### Test Team Search:
1. Run the test script: `python test_team_search.py`
2. Try searching for "5454" in the web interface
3. Try searching for "Team 5454" in the web interface
4. Both should return the same results

### Monitor API Sync:
1. Visit `/api/sync-status` in your browser
2. Check console output for sync messages
3. Monitor database for new/updated records

## Configuration

No additional configuration required. The auto-sync will use your existing API configuration:
- Current event code from `config/game_config.json`
- API credentials from your existing setup
- Dual API fallback system (FIRST API → TBA API)

## Performance Notes

- API sync runs every 3 minutes to balance freshness with API rate limits
- Only syncs data for the configured event to minimize load
- Uses the existing dual API system with fallback
- Graceful error handling ensures the system keeps running even if one sync fails
- Background threads are daemon threads so they don't prevent shutdown
