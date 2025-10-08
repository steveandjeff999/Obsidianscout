# API-Based Upcoming Matches Feature

## Overview
The Now Brief panel's "Upcoming Matches" section now intelligently determines which matches to display by checking the FRC API (FIRST Inspires or The Blue Alliance) for the last completed match with scores, then showing the next 5 matches after that point.

## How It Works

### 1. API Check (Primary)
When loading the Now Brief panel, the system:
1. Fetches all matches for the current event from the API using `get_matches_dual_api()`
2. Scans through the API response to find the highest match number that has final scores (`red_score` and `blue_score` are not null)
3. Uses this match number as the starting point
4. Queries the local database for the next 5 matches after this point

### 2. Local Database Fallback
If the API call fails (timeout, authentication error, no data, etc.), the system:
1. Falls back to querying the local database
2. Finds the last match in the local DB with recorded scores
3. Shows the next 5 matches after that point

### 3. Default Behavior
If neither the API nor local DB have any completed matches with scores:
- Shows the first 5 matches from the local database
- This typically happens at the start of an event before any matches have been played

## API Data Sources

### FIRST Inspires API
The system uses the following endpoints:
- `/v2.0/{season}/matches/{event_code}` - Returns matches with final scores
- `/v2.0/{season}/schedule/{event_code}/qual` - Qualification match schedule
- `/v2.0/{season}/schedule/{event_code}/playoff` - Playoff match schedule

Match scores are indicated by:
- `scoreRedFinal` - Red alliance final score
- `scoreBlueFinal` - Blue alliance final score

### The Blue Alliance API
Alternative endpoints when TBA is preferred:
- `/event/{event_key}/matches` - Returns all matches with scores

Match scores are indicated by:
- `alliances.red.score` - Red alliance score
- `alliances.blue.score` - Blue alliance score
- `winning_alliance` - Indicates which alliance won

## Configuration

### API Settings
The system respects the following configuration (in `app_config.json` or game config):

```json
{
  "preferred_api_source": "first",  // or "tba"
  "api_settings": {
    "username": "your_username",
    "auth_token": "your_token",
    "base_url": "https://frc-api.firstinspires.org",
    "auto_sync_enabled": true
  },
  "tba_api_settings": {
    "auth_key": "your_tba_key",
    "base_url": "https://www.thebluealliance.com/api/v3"
  }
}
```

## Benefits

1. **Real-Time Updates**: Shows truly upcoming matches based on live competition progress
2. **Automatic Progression**: As matches are completed and scored, the panel automatically shows the next relevant matches
3. **Resilient**: Falls back gracefully to local data if API is unavailable
4. **Multi-API Support**: Works with both FIRST Inspires and The Blue Alliance APIs
5. **No Manual Updates**: Scouts don't need to manually scroll to find current matches

## Technical Details

### Code Location
- **Main Logic**: `app/routes/main.py` - `api_brief_data()` function
- **API Utilities**: `app/utils/api_utils.py` - `get_matches_dual_api()` function
- **UI Display**: `app/templates/partials/brief_panel.html` - JavaScript rendering

### Match Number Comparison
The system uses `match_number` field for ordering:
- Qualification matches: 1, 2, 3, ...
- Playoff matches: Continue with higher numbers or use separate ordering

### Performance Considerations
- API calls are only made when loading the brief panel (not on every page load)
- Results are cached client-side for 60 seconds
- API timeout is set to 15 seconds to prevent hanging
- Failures log warnings but don't break the page

## Error Handling

The system handles various failure scenarios:

1. **API Authentication Failure**: Falls back to local DB
2. **API Timeout**: Falls back to local DB after 15 seconds
3. **Invalid Event Code**: Falls back to local DB
4. **No Matches Found**: Shows empty state with helpful message
5. **Partial Data**: Uses whatever data is available (API or local)

## Logging

The system logs important events:
```python
current_app.logger.info(f"Last completed match from API: {match_num}")
current_app.logger.warning(f"Could not fetch matches from API, using local DB: {error}")
```

Check application logs to diagnose API issues.

## Future Enhancements

Potential improvements:
1. Cache API results for a configurable duration
2. Show match times from API (scheduled_time field)
3. Display match status indicators (upcoming, in progress, completed)
4. Add real-time WebSocket updates for live match progression
5. Show estimated time until next match
6. Filter by match type (qual, playoff, practice)
