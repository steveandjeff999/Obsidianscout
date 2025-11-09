# Offseason Team Remapping Fix - Complete Implementation

## Problem

Offseason FRC events sometimes have multiple teams from the same organization (e.g., 581B, 581C, 1678B, 1678C, 1678D). The Blue Alliance API returns these in two different formats:

1. **Teams API** (`/event/{eventcode}/teams`): Returns the 99xx numeric equivalents (9989, 9988, 9997, 9996, 9986, etc.)
2. **Matches/Schedule API** (`/event/{eventcode}/matches`): Returns the letter-suffix identifiers (581B, 581C, 1678B, etc.)

This mismatch caused `ValueError: invalid literal for int() with base 10: '581B'` when the system tried to parse team numbers.

## Solution

Implemented comprehensive team remapping using TBA's `remap_teams` field, which provides the mapping between letter-suffix teams and their 99xx equivalents.

### Key Changes

#### 1. **app/utils/tba_api_utils.py** - Core Remapping Logic

- **Added global cache** for `remap_teams` data per event
- **`get_event_team_remapping(event_key)`**: Fetches and caches the remap_teams dictionary from TBA's event endpoint
  - Returns format: `{"581B": 9989, "1678C": 9996, ...}`
  
- **`remap_team_number(team_identifier, event_key)`**: Remaps any team identifier using the event's mapping
  - Handles various formats: `"581B"`, `"frc581B"`, `5454`, `"5454"`
  - Returns integer for remapped/numeric teams, uppercase string if no mapping found
  - Examples:
    - `remap_team_number("581B", "2025casj")` → `9989`
    - `remap_team_number("1678C", "2025casj")` → `9996`
    - `remap_team_number("5454", "2025casj")` → `5454`

- **Updated `get_tba_event_details()`**: Automatically caches `remap_teams` when fetching event details

- **Updated `tba_team_to_db_format()`**: Added `event_key` parameter to apply remapping during team conversion

- **Updated `tba_match_to_db_format()`**: Added `event_key` parameter and remaps all alliance team numbers
  - Extracts event_key from match key if not provided
  - Applies remapping to red and blue alliance teams

#### 2. **app/utils/api_utils.py** - Integration Points

- **Added imports** for `remap_team_number` and `get_event_team_remapping`

- **Updated `get_teams_dual_api()`**: Passes `event_key` to `tba_team_to_db_format()` in all code paths (primary and fallback)

- **Updated `get_matches_dual_api()`**: Passes `event_key` to `tba_match_to_db_format()` in all code paths

- **Updated `api_to_db_match_conversion()`**: Remaps team numbers when processing TBA format matches
  - Extracts event_key from match key
  - Applies remapping to both alliances

#### 3. **app/routes/mobile_api.py** - Mobile API Safety

- **Updated graph generation endpoint**: Uses `safe_int_team_number()` to handle team identifiers with letters gracefully

#### 4. **tools/tk_mobile_gameconfig_ui.py** - UI Tool Safety

- **Updated login/auth**: Uses try/except for team number conversion, falls back to sending original string

### How It Works

1. **Event Details Fetch**: When fetching event details from TBA, the system automatically caches any `remap_teams` data
   ```python
   event_data = get_tba_event_details("2025casj")
   # Automatically caches: {"581B": 9989, "1678C": 9996, ...}
   ```

2. **Team Sync**: When syncing teams from TBA, the system applies remapping:
   ```python
   team_data = tba_team_to_db_format(tba_team, event_key="2025casj")
   # If TBA returned team 9989, it stays 9989
   # If somehow "581B" appears, it maps to 9989
   ```

3. **Match Sync**: When syncing matches, all alliance teams are remapped:
   ```python
   # TBA match has: red=["frc581B", "frc1678C", ...], blue=[...]
   match_data = tba_match_to_db_format(tba_match, event_id, event_key="2025casj")
   # Result: red_alliance="9989,9996,..." (letter suffixes converted to numeric)
   ```

4. **Consistency**: All team numbers stored in the database are now integers (or their 99xx equivalents), eliminating type mismatches

### TBA Remap Format

From [TBA PR #8028](https://github.com/the-blue-alliance/the-blue-alliance/pull/8028), TBA's `remap_teams` format:

```json
{
  "frc9971": "frc971B",
  "frc9973": "frc973B",
  "frc9982": "frc6647B",
  "frc9984": "frc841B",
  "frc9985": "frc6657B",
  "frc9986": "frc1678D",
  "frc9987": "frc5940B",
  "frc9988": "frc581C",
  "frc9989": "frc581B",
  "frc9990": "frc5419B",
  "frc9991": "frc5026B",
  "frc9992": "frc4698B",
  "frc9993": "frc2813B",
  "frc9994": "frc254B",
  "frc9995": "frc2073B",
  "frc9996": "frc1678C",
  "frc9997": "frc1678B",
  "frc9998": "frc1323C",
  "frc9999": "frc1323B"
}
```

## Testing

Run the comprehensive test suite:

```powershell
& ".\.venv\Scripts\python.exe" test_team_remapping.py
```

**Test Coverage:**
- ✓ `safe_int_team_number()` utility (8 test cases)
- ✓ `remap_team_number()` with various inputs (10 test cases)
- ✓ `tba_match_to_db_format()` with letter-suffix teams
- ✓ All tests pass

## Benefits

1. **No More ValueError**: Letter-suffix teams like "581B" are handled gracefully
2. **Automatic Remapping**: System fetches and caches remap_teams from TBA
3. **Consistent Data**: Database always stores integer team numbers (or 99xx equivalents)
4. **Backward Compatible**: Regular numeric teams continue to work as before
5. **Comprehensive**: Covers all API entry points (teams, matches, mobile API, tools)

## Files Modified

- `app/utils/tba_api_utils.py` - Core remapping logic
- `app/utils/api_utils.py` - Integration with existing API functions
- `app/routes/mobile_api.py` - Mobile API safety
- `tools/tk_mobile_gameconfig_ui.py` - UI tool safety
- `test_team_remapping.py` - Comprehensive test suite (NEW)

## Usage Example

```python
from app.utils.tba_api_utils import remap_team_number

# Offseason event with letter-suffix teams
result = remap_team_number("581B", event_key="2025casj")
# Returns: 9989

result = remap_team_number("1678C", event_key="2025casj")
# Returns: 9996

# Regular team (no remapping needed)
result = remap_team_number("5454", event_key="2025casj")
# Returns: 5454
```

## References

- [TBA PR #8028 - Offseason Demo Teams](https://github.com/the-blue-alliance/the-blue-alliance/pull/8028)
- [TBA API Documentation](https://www.thebluealliance.com/apidocs/v3)
