# Prediction Data Filtering Fix

## Issue
Predictions in `/matches/predict` and `/matches/predict_all` were only showing data for team 5454 and not using data from other teams that were visible in `/data/manage`.

## Root Cause
The `calculate_team_metrics()` function was being called **without an event_id parameter**, causing it to aggregate data from ALL events in the database, not just the current event. This meant:

1. Teams with recent API updates (like 5454) would have their newer cross-event data dominate
2. Teams with data only in the current event wouldn't show properly in predictions
3. The behavior didn't match `/data/manage` which filters by the current event

## Solution
Updated `predict_match_outcome()` and `generate_match_strategy_analysis()` functions to:

1. **Pass `event_id=match.event_id`** to all `calculate_team_metrics()` calls
2. **Add event filtering** to all scouting_records queries using `.join(Match).filter(Match.event_id == match.event_id)`

This ensures predictions only use scouting data from the match's event, making the behavior consistent with how users see data in `/data/manage`.

## Files Changed
- `app/utils/analysis.py`:
  - `predict_match_outcome()`: Added `event_id=match.event_id` parameter to `calculate_team_metrics()` calls for both red and blue alliances
  - `generate_match_strategy_analysis()`: Added `event_id=match.event_id` parameter and event filtering to scouting_records queries for both alliances

## Technical Details

### Before Fix
```python
# This used ALL events' data
analytics_result = calculate_team_metrics(team.id, game_config=team_config)
```

### After Fix
```python
# This uses only the match's event data
analytics_result = calculate_team_metrics(team.id, event_id=match.event_id, game_config=team_config)
```

### Scouting Records Filtering
```python
# Added event filter to all scouting_records queries
scouting_records = filter_scouting_data_by_scouting_team()\\
    .filter(ScoutingData.team_id == team.id)\\
    .join(Match).filter(Match.event_id == match.event_id).all()
```

## Testing
After this fix, predictions should now:
- ✅ Use data from all teams in the current event (matching `/data/manage`)
- ✅ Show accurate predictions based on event-specific performance
- ✅ Not mix data from different events
- ✅ Work consistently with the scouting team isolation model

## Date
October 4, 2025
