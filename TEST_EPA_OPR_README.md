# EPA/OPR History API Test Script

A Tkinter-based test client for the `/api/mobile/config/game/stats/epa-opr-history` endpoint.

## Overview

This script provides an interactive UI to:
1. **Login** to the mobile API using credentials and team number
2. **Select an event** by ID, code, or year-prefixed code
3. **Fetch EPA and OPR data** for teams at that event
4. **View results** in a table format with per-match details

## Features

- **Tabbed Interface**: 4 tabs for Login → Event → Fetch → Results workflow
- **Team Data Table**: Shows OPR, DPR, CCWM ratings for each team
- **Match Details**: Double-click a team to view per-match EPA breakdown
- **Configurable Limits**: Set max matches per team (default 200, max 500)
- **Selective Team Fetching**: Fetch all teams or specific team numbers
- **Real-time Status**: Live feedback on login, fetch, and errors

## Usage

### Prerequisites

```bash
pip install requests
```

### Running the Script

```bash
python test_epa_opr_history.py
```

### Workflow

#### Tab 1: Login
1. **API Base URL**: Leave as `http://localhost:5000/api/mobile` or update if running remotely
2. **Username**: Enter your scouting team username
3. **Password**: Enter the password for that user
4. **Team Number**: Enter your scouting team number (e.g., `5454`)
5. Click **Login** button

If successful, you'll see "✓ Logged in as..." and move to Tab 2.

#### Tab 2: Select Event
1. **Event ID**: Enter one of:
   - Numeric database ID: `123`
   - Year-prefixed code: `2026OKTU`
   - Raw code: `OKTU` (auto-resolved to current season)
2. **Team Numbers** (optional): Leave blank for all teams, or enter comma-separated list:
   - `254,1678,971`
3. **Max Matches per Team**: Default is 200 (adjust if needed)

#### Tab 3: Fetch EPA/OPR
- Click **Fetch EPA/OPR History** to request data
- Watch the progress bar and status updates
- If successful, automatically moves to Tab 4

#### Tab 4: Results
- **Table View**: Shows team summaries with OPR/DPR/CCWM ratings
- **Double-click any team** to see:
  - Per-match breakdown with EPA estimates
  - Auto, Teleop, and Endgame point splits
  - Match timing and alliance assignment
  - Raw JSON data

## Data Displayed

### Team Summary (Table)
| Column | Source | Description |
|--------|--------|-------------|
| Team # | API | Team number |
| Team Name | API | Team name from database |
| OPR | TBA | Offensive Power Rating |
| DPR | TBA | Defensive Power Rating |
| CCWM | TBA | Contribution to Winning Margin |
| # Matches | Statbotics | Number of matches with EPA data |

### Match Details (Detail View)
- **OPR Data**: Event-level statistics from The Blue Alliance
- **Per-Match EPA**: Historical match-by-match estimates from Statbotics
  - Match number and competition level (qm, ef, qf, sf, f)
  - Alliance (red/blue)
  - EPA breakdown: Total, Auto, Teleop, Endgame

## API Reference

### Endpoint
```
POST /api/mobile/config/game/stats/epa-opr-history
```

### Request Body
```json
{
  "event_id": "2026OKTU",
  "team_numbers": [254, 1678],
  "limit": 200
}
```

### Response
```json
{
  "success": true,
  "event_code": "OKTU",
  "tba_event_key": "2026oktu",
  "teams": [
    {
      "team_number": 254,
      "team_name": "The Cheesy Poofs",
      "match_epa_history": [...],
      "opr_data": {
        "opr": 45.3,
        "dpr": 15.2,
        "ccwm": 8.1
      }
    }
  ]
}
```

## Error Handling

The script handles several error scenarios:

- **Connection errors**: Shows error message if server is unreachable
- **Authentication errors**: Displays login failure reason (invalid credentials, inactive account)
- **Event not found**: Returns when event doesn't exist or isn't accessible
- **API errors**: Shows raw error message from server

## Troubleshooting

### "Connection refused" error
- Verify the server is running on the configured port
- Check API base URL is correct (default: `http://localhost:5000/api/mobile`)

### "Invalid credentials" error
- Verify username, password, and team number are correct
- Check that the user account is active

### "Event not found" error
- Try using numeric event ID format
- Try full year-prefixed code: `2026OKTU` instead of `OKTU`
- Check that event exists in database

### No teams returned
- Verify teams have participated in the selected event
- Check that your scouting team has access to those teams
- Try fetching all teams (leave team numbers blank)

## Data Sources

- **EPA Data**: Statbotics API (per-match historical estimates)
- **OPR Data**: The Blue Alliance API (event-level rankings)

## Notes

- EPA/OPR data availability depends on whether the external APIs have processed the event
- Historical data may take time to appear after matches are played
- The script caches token for the session; you can login as different users by entering new credentials

## License

Same as OBSIDIAN Scout project
