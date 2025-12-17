# Full-Featured FRC Scout API Documentation

## Overview
This API provides comprehensive access to all teams, events, matches, and scouting data in the database. The API uses Bearer token authentication with API keys that can be created through the admin interface.

**Base URL:** `https://your-domain.com/api/v1`

**Authentication:** Include `Authorization: Bearer YOUR_API_KEY` in request headers

## Core Endpoints

### 1. API Information
**GET /info**
- Get API version, endpoints, and current API key information
- Returns: API key details, available endpoints, server time

### 2. Teams

#### List All Teams
**GET /teams**
- Get all teams with optional filtering and pagination
- **Query Parameters:**
  - `event_id` (int): Filter teams by event
  - `team_number` (int): Filter by specific team number
  - `scouting_team_number` (int): Filter by scouting team
  - `limit` (int): Number of results (max 1000, default 100)
  - `offset` (int): Pagination offset (default 0)
- **Response:** List of teams with total count and pagination info

#### Get Team Details
**GET /teams/{team_id}**
- Get detailed information about a specific team
- **Response:** Team info, events, recent matches, scouting data count

### 3. Events

#### List All Events
**GET /events**
- Get all events with optional filtering and pagination
- **Query Parameters:**
  - `code` (string): Filter by event code (partial match)
  - `location` (string): Filter by location (partial match)
  - `limit` (int): Number of results (max 1000, default 100)
  - `offset` (int): Pagination offset (default 0)
- **Response:** List of events with total count and pagination info

#### Get Event Details
**GET /events/{event_id}**
- Get detailed information about a specific event
- **Response:** Event info, participating teams, recent matches

### 4. Matches

#### List All Matches
**GET /matches**
- Get all matches with optional filtering and pagination
- **Query Parameters:**
  - `event_id` (int): Filter matches by event
  - `match_type` (string): Filter by match type (partial match)
  - `team_number` (int): Filter matches involving specific team
  - `match_number` (int): Filter by specific match number
  - `limit` (int): Number of results (max 1000, default 100)
  - `offset` (int): Pagination offset (default 0)
- **Response:** List of matches with total count and pagination info

#### Get Match Details
**GET /matches/{match_id}**
- Get detailed information about a specific match
- **Response:** Match info, alliances, scores, scouting entries

### 5. Scouting Data

#### List All Scouting Data
**GET /scouting-data**
- Get all scouting data with optional filtering and pagination
- **Query Parameters:**
  - `team_id` (int): Filter by team
  - `match_id` (int): Filter by match
  - `scouting_team_number` (int): Filter by scouting team
  - `scout` (string): Filter by scout name (partial match)
  - `limit` (int): Number of results (max 1000, default 100)
  - `offset` (int): Pagination offset (default 0)
- **Response:** List of scouting entries with total count and pagination info

#### Create Scouting Data
**POST /scouting-data**
- Create new scouting data entry
- **Required Fields:**
  - `team_id` (int): ID of the team being scouted
  - `match_id` (int): ID of the match
  - `data` (object): Scouting data payload
  - `scout` (string): Name/ID of scout
- **Response:** Created scouting data entry with ID and timestamp

### 6. Analytics

#### Team Performance Analytics
**GET /analytics/team-performance**
- Get performance analytics for any team
- **Query Parameters:**
  - `team_id` (int): Team ID (required if no team_number)
  - `team_number` (int): Team number (required if no team_id)
  - `event_id` (int): Optional - limit analytics to specific event
- **Response:** Analytics including total entries, unique matches, data quality score

### 7. Sync Operations

#### Get Sync Status
**GET /sync/status**
- Get current sync status and data counts
- **Response:** Data counts for all entities, last check time, sync availability

#### Trigger Sync
**POST /sync/trigger**
- Trigger sync operation
- **Body Parameters:**
  - `type` (string): Sync type - "full", "teams", "matches", "scouting_data"
- **Response:** Sync ID and estimated completion time

### 8. Team Lists

#### Do Not Pick List
**GET /team-lists/do-not-pick**
- Get do not pick list entries for requesting team
- **Response:** List of teams marked as do not pick with reasons

### 9. Health Check
**GET /health**
- Check API health and status
- **Response:** Health status, timestamp, API version

## API Features

### Pagination
Most list endpoints support pagination:
- `limit`: Number of results per page (max 1000, default 100)
- `offset`: Number of results to skip (default 0)
- Response includes `count`, `total_count`, `limit`, and `offset`

### Filtering
Endpoints support various filtering options:
- Exact matches for IDs and numbers
- Partial matches (case-insensitive) for text fields
- Multiple filter combinations supported

### Error Handling
All endpoints return structured error responses:
```json
{
  "error": "Error description",
  "code": "ERROR_CODE"  // When applicable
}
```

Common HTTP status codes:
- `200`: Success
- `201`: Created (for POST requests)
- `400`: Bad Request (missing/invalid parameters)
- `401`: Unauthorized (invalid/missing API key)
- `403`: Forbidden (insufficient permissions)
- `404`: Not Found (resource doesn't exist)
- `500`: Internal Server Error

### Permissions
API keys have different permission levels:
- `team_data_access`: Access teams, events, basic data
- `scouting_data_read`: Read scouting data and matches
- `scouting_data_write`: Create scouting data entries
- `analytics_access`: Access analytics endpoints
- `sync_operations`: Access sync endpoints

## Example Usage

### Python Example
```python
import requests

API_KEY = "your_api_key_here"
BASE_URL = "https://your-domain.com/api/v1"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Get all teams
response = requests.get(f"{BASE_URL}/teams", headers=headers)
teams = response.json()

# Get teams from specific event
response = requests.get(f"{BASE_URL}/teams", 
                       headers=headers, 
                       params={"event_id": 1})
event_teams = response.json()

# Get matches involving team 254
response = requests.get(f"{BASE_URL}/matches", 
                       headers=headers, 
                       params={"team_number": 254})
team_matches = response.json()

# Create scouting data
scouting_data = {
    "team_id": 1,
    "match_id": 1,
    "scout": "John Doe",
    "data": {"autonomous": 5, "teleop": 10}
}
response = requests.post(f"{BASE_URL}/scouting-data", 
                        headers=headers, 
                        json=scouting_data)
```

### cURL Example
```bash
# Get API info
curl -H "Authorization: Bearer YOUR_API_KEY" \
     https://your-domain.com/api/v1/info

# Get all teams with pagination
curl -H "Authorization: Bearer YOUR_API_KEY" \
     "https://your-domain.com/api/v1/teams?limit=50&offset=0"

# Get team performance analytics
curl -H "Authorization: Bearer YOUR_API_KEY" \
     "https://your-domain.com/api/v1/analytics/team-performance?team_number=254"
```

## Rate Limiting
API keys have configurable rate limits (requests per hour). Default is 1000 requests/hour. Monitor your usage and contact administrators for higher limits if needed.

## Data Access Philosophy
This API provides access to ALL data in the system, not just team-specific data. This enables:
- Cross-team analysis and comparison
- Complete tournament statistics
- Comprehensive scouting insights
- Full data export capabilities

Use filtering parameters to focus on specific subsets of data as needed.