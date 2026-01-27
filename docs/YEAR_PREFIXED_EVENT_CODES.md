# Year-Prefixed Event Codes

## Overview

Starting in the 2026 season, OBSIDIAN Scout stores event codes with a **year prefix** to differentiate the same event across different seasons. This allows teams to maintain historical scouting data while ensuring current season data is properly isolated.

## Format

| Component | Description | Example |
|-----------|-------------|---------|
| Year Prefix | 4-digit season year | `2026` |
| Event Code | FRC event code | `OKTU` |
| Full Code | Year + Event | `2026OKTU` |

### Examples
- `2025OKTU` - Oklahoma Regional 2025
- `2026OKTU` - Oklahoma Regional 2026
- `2026ARLI` - Arkansas Regional 2026
- `2026MOKS` - Greater Kansas City Regional 2026

## Configuration

The season is configured in each team's `game_config.json`:

```json
{
  "season": 2026,
  "current_event_code": "OKTU",
  "game_name": "REEFSCAPE"
}
```

- `season` - The year prefix used for database storage
- `current_event_code` - The raw event code (without year prefix)

## How It Works

### Database Storage
Events are stored with year-prefixed codes in the database:
```sql
SELECT code, name, year FROM events WHERE scouting_team_number = 5454;
-- Returns: 2026OKTU, Oklahoma Regional, 2026
```

### External API Calls
When fetching data from FIRST API or The Blue Alliance:
- The year prefix is **stripped** before making API calls
- External APIs use raw event codes (e.g., `OKTU`)
- Example: `https://frc-api.firstinspires.org/v2.0/2026/teams/event/OKTU`

### Internal Lookups
When looking up events in the database:
1. Try year-prefixed code first (e.g., `2026OKTU`)
2. Fall back to raw code for backwards compatibility (e.g., `OKTU`)

## Automatic Resolution

### Mobile API
The mobile API automatically resolves raw event codes to year-prefixed versions:

```
Request: GET /api/mobile/matches?event_id=OKTU
         (with team configured for season 2026)

Resolution: 
  1. Load team's game_config.json → season: 2026
  2. Construct year-prefixed code: "2026OKTU"
  3. Query database for "2026OKTU"
  4. Fall back to "OKTU" if not found
```

### Web Interface
All web pages and dropdowns display events with their year for clarity:
- "Oklahoma Regional (2026)"
- "Arkansas Regional (2026)"

## Affected Components

### Files Updated for Year-Prefix Support

| File | Purpose |
|------|---------|
| `app/utils/team_isolation.py` | `get_event_by_code()` helper with auto-resolution |
| `app/utils/api_utils.py` | `strip_year_prefix()` for external API calls |
| `app/utils/match_time_fetcher.py` | Background match time updates |
| `app/utils/schedule_adjuster.py` | Schedule adjustment processing |
| `app/routes/mobile_api.py` | `resolve_event_code_to_id()` helper |
| `app/routes/matches.py` | Match sync and time updates |
| `app/routes/teams.py` | Team sync operations |
| `app/routes/notifications.py` | Notification scheduling |
| `app/routes/alliances.py` | Alliance event lookups |
| `run.py` | Event syncing from config |

### Template Updates
All event dropdowns now display the year:
- `teams/index.html`
- `matches/index.html`
- `scouting/index.html`
- `pit_scouting/index.html`
- `analytics/config_averages.html`
- And more...

## Best Practices

### For Mobile App Developers
1. **Prefer numeric event IDs** - Most reliable, obtained from `/api/mobile/events`
2. **Year-prefixed codes work** - Use `2026OKTU` for explicit control
3. **Raw codes auto-resolve** - `OKTU` resolves based on team's season config

### For System Administrators
1. **Set season correctly** - Ensure `game_config.json` has correct season year
2. **Sync events fresh each season** - Don't carry over old event data
3. **Check year prefixes** - Verify events have correct year prefix in database

## Backwards Compatibility

The system maintains backwards compatibility:
- Raw event codes (e.g., `OKTU`) still work for older data
- Lookups try year-prefixed first, then fall back to raw
- External API calls always use raw codes

## Troubleshooting

### "Event not found" Errors
If you see "Event OKTU not found, available: 2025OKTU, 2026OKTU":
1. Check your `game_config.json` has correct `season` value
2. Ensure the event was synced for the current season
3. Use the full year-prefixed code explicitly

### Multiple Events with Same Code
This is expected behavior! Each season creates a new event record:
- `2025OKTU` (id: 1) - 2025 data
- `2026OKTU` (id: 4) - 2026 data

The system uses your configured season to pick the right one.

## Version History

- **January 2026** - Initial implementation for 2026 season
- Supports multi-year event tracking
- Mobile API auto-resolution
- Web interface year display
