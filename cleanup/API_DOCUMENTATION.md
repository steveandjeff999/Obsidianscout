# FRC Scout API Documentation

## Overview

The FRC Scout API provides programmatic access to your team's scouting data, allowing you to integrate with external applications, build custom dashboards, and automate data workflows. The API uses REST principles and JSON for data exchange.

## Base URL

```
https://your-scout-domain.com/api/v1
```

## Authentication

### API Keys

The API uses API key authentication. Team admins can create up to 5 API keys per team through the web interface.

**Header Authentication (Recommended):**
```http
Authorization: Bearer sk_live_your_api_key_here
```

**Alternative Header:**
```http
X-API-Key: sk_live_your_api_key_here
```

**Query Parameter (GET requests only):**
```http
GET /api/v1/teams?api_key=sk_live_your_api_key_here
```

### Creating API Keys

1. Log in to your Scout platform as a team admin
2. Navigate to **Administration > API Keys**
3. Click "Create API Key"
4. Provide a name and configure settings
5. Copy the key immediately (it won't be shown again)

### API Key Format

API keys follow the format: `sk_live_` followed by 32 random characters.

Example: `sk_live_abc123def456ghi789jkl012mno345pqr`

## Rate Limits

API keys have configurable rate limits (100-5000 requests per hour). Rate limits are enforced per hour and reset at the beginning of each hour.

**Rate Limit Headers:**
- `X-RateLimit-Limit`: Maximum requests per hour
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Unix timestamp when the limit resets

## Permissions

API keys have granular permissions:

- **team_data_access**: Access to team and event data
- **scouting_data_read**: Read scouting data entries
- **scouting_data_write**: Create/modify scouting data
- **sync_operations**: Trigger sync operations
- **analytics_access**: Access analytics endpoints

## Team Isolation

All API requests are automatically scoped to your team's data. You cannot access data from other teams unless explicitly shared through scouting alliances.

## Response Format

All responses follow a consistent JSON format:

**Success Response:**
```json
{
  "success": true,
  "data": { ... },
  "count": 10,
  "message": "Optional message"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Error description",
  "code": "ERROR_CODE"
}
```

## Error Codes

| Code | Description |
|------|-------------|
| `INVALID_API_KEY` | API key is invalid or expired |
| `INSUFFICIENT_PERMISSIONS` | API key lacks required permission |
| `RATE_LIMIT_EXCEEDED` | Too many requests |
| `VALIDATION_ERROR` | Request data is invalid |
| `NOT_FOUND` | Requested resource not found |

## Endpoints

### API Information

#### Get API Info
```http
GET /api/v1/info
```

Returns information about your API key and available endpoints.

**Response:**
```json
{
  "success": true,
  "api_version": "1.0",
  "api_key": {
    "id": 1,
    "name": "Dashboard Integration",
    "team_number": 1234,
    "permissions": { ... },
    "rate_limit_per_hour": 1000
  },
  "server_time": "2025-09-16T10:30:00Z",
  "endpoints": { ... }
}
```

### Teams

#### List Teams
```http
GET /api/v1/teams
```

Get all teams associated with your scouting team.

**Parameters:**
- `event_id` (optional): Filter by event ID

**Response:**
```json
{
  "success": true,
  "teams": [
    {
      "id": 1,
      "team_number": 1234,
      "team_name": "Example Team",
      "location": "City, State",
      "events": [
        {
          "id": 1,
          "name": "District Event",
          "code": "2025test"
        }
      ]
    }
  ],
  "count": 1,
  "requesting_team": 1234
}
```

#### Get Team Details
```http
GET /api/v1/teams/{team_id}
```

Get detailed information about a specific team.

**Response:**
```json
{
  "success": true,
  "team": {
    "id": 1,
    "team_number": 1234,
    "team_name": "Example Team",
    "location": "City, State",
    "scouting_data_count": 25,
    "recent_matches": [
      {
        "id": 1,
        "match_number": 1,
        "match_type": "qualification",
        "red_alliance": "1234,5678,9012",
        "blue_alliance": "3456,7890,1234",
        "red_score": 150,
        "blue_score": 120,
        "winner": "red"
      }
    ]
  }
}
```

### Events

#### List Events
```http
GET /api/v1/events
```

Get all events in the system.

**Response:**
```json
{
  "success": true,
  "events": [
    {
      "id": 1,
      "name": "District Championship",
      "code": "2025test",
      "location": "Convention Center",
      "start_date": "2025-03-15T09:00:00Z",
      "end_date": "2025-03-17T18:00:00Z",
      "team_count": 48
    }
  ],
  "count": 1
}
```

### Matches

#### List Matches
```http
GET /api/v1/matches
```

Get matches for your team.

**Parameters:**
- `event_id` (optional): Filter by event
- `match_type` (optional): Filter by match type
- `limit` (optional): Maximum results (default 100, max 1000)

**Response:**
```json
{
  "success": true,
  "matches": [
    {
      "id": 1,
      "match_number": 1,
      "match_type": "qualification",
      "event_id": 1,
      "red_alliance": "1234,5678,9012",
      "blue_alliance": "3456,7890,1234",
      "red_score": 150,
      "blue_score": 120,
      "winner": "red"
    }
  ],
  "count": 1,
  "limit_applied": 100
}
```

### Scouting Data

#### List Scouting Data
```http
GET /api/v1/scouting-data
```

Get scouting data entries for your team.

**Parameters:**
- `team_id` (optional): Filter by team
- `match_id` (optional): Filter by match
- `limit` (optional): Maximum results (default 100, max 1000)

**Response:**
```json
{
  "success": true,
  "scouting_data": [
    {
      "id": 1,
      "team_id": 1,
      "match_id": 1,
      "data": {
        "auto_points": 15,
        "teleop_points": 45,
        "endgame_points": 20
      },
      "scout": "john_doe",
      "timestamp": "2025-03-15T14:30:00Z"
    }
  ],
  "count": 1,
  "limit_applied": 100
}
```

#### Create Scouting Data
```http
POST /api/v1/scouting-data
```

Create a new scouting data entry.

**Request Body:**
```json
{
  "team_id": 1,
  "match_id": 1,
  "data": {
    "auto_points": 15,
    "teleop_points": 45,
    "endgame_points": 20
  },
  "scout": "john_doe"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Scouting data created successfully",
  "scouting_data": {
    "id": 2,
    "team_id": 1,
    "match_id": 1,
    "scout": "john_doe",
    "timestamp": "2025-03-15T14:30:00Z"
  }
}
```

### Analytics

#### Team Performance
```http
GET /api/v1/analytics/team-performance
```

Get performance analytics for a team.

**Parameters:**
- `team_id` (required): Team to analyze
- `event_id` (optional): Specific event

**Response:**
```json
{
  "success": true,
  "analytics": {
    "team_id": 1,
    "team_number": 1234,
    "team_name": "Example Team",
    "total_scouting_entries": 25,
    "unique_matches_scouted": 12,
    "data_quality_score": 85.5,
    "last_scouted": "2025-03-15T16:45:00Z"
  }
}
```

### Sync Operations

#### Sync Status
```http
GET /api/v1/sync/status
```

Get current sync status and data counts.

**Response:**
```json
{
  "success": true,
  "sync_status": {
    "team_number": 1234,
    "last_check": "2025-03-15T17:00:00Z",
    "data_counts": {
      "teams": 48,
      "matches": 120,
      "scouting_data": 450
    },
    "sync_available": true
  }
}
```

#### Trigger Sync
```http
POST /api/v1/sync/trigger
```

Trigger a sync operation.

**Request Body:**
```json
{
  "type": "full"
}
```

**Types:**
- `full`: Sync all data
- `teams`: Sync team data only
- `matches`: Sync match data only
- `scouting_data`: Sync scouting data only

**Response:**
```json
{
  "success": true,
  "message": "Full sync triggered successfully",
  "sync_id": "sync_1710517800",
  "estimated_completion": "2025-03-15T17:05:00Z"
}
```

### Team Lists

#### Do Not Pick List
```http
GET /api/v1/team-lists/do-not-pick
```

Get your team's "do not pick" list.

**Response:**
```json
{
  "success": true,
  "do_not_pick_list": [
    {
      "id": 1,
      "team_id": 5,
      "team_number": 5678,
      "team_name": "Problem Team",
      "reason": "Poor collaboration",
      "timestamp": "2025-03-15T12:00:00Z"
    }
  ],
  "count": 1
}
```

### Health Check

#### API Health
```http
GET /api/v1/health
```

Check API health and connectivity.

**Response:**
```json
{
  "success": true,
  "status": "healthy",
  "timestamp": "2025-03-15T17:00:00Z",
  "version": "1.0",
  "team_number": 1234
}
```

## Code Examples

### Python

```python
import requests
import json

# Configuration
API_BASE = "https://your-scout-domain.com/api/v1"
API_KEY = "sk_live_your_api_key_here"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Get team data
response = requests.get(f"{API_BASE}/teams", headers=headers)
teams = response.json()

if teams["success"]:
    for team in teams["teams"]:
        print(f"Team {team['team_number']}: {team['team_name']}")
else:
    print(f"Error: {teams['error']}")

# Create scouting data
scouting_data = {
    "team_id": 1,
    "match_id": 1,
    "data": {
        "auto_points": 15,
        "teleop_points": 45,
        "endgame_points": 20
    },
    "scout": "api_user"
}

response = requests.post(
    f"{API_BASE}/scouting-data", 
    headers=headers,
    json=scouting_data
)

result = response.json()
if result["success"]:
    print("Scouting data created successfully!")
else:
    print(f"Error: {result['error']}")
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');

const API_BASE = 'https://your-scout-domain.com/api/v1';
const API_KEY = 'sk_live_your_api_key_here';

const headers = {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
};

// Get team data
async function getTeams() {
    try {
        const response = await axios.get(`${API_BASE}/teams`, { headers });
        
        if (response.data.success) {
            response.data.teams.forEach(team => {
                console.log(`Team ${team.team_number}: ${team.team_name}`);
            });
        } else {
            console.error('Error:', response.data.error);
        }
    } catch (error) {
        console.error('Request failed:', error.message);
    }
}

// Create scouting data
async function createScoutingData() {
    const data = {
        team_id: 1,
        match_id: 1,
        data: {
            auto_points: 15,
            teleop_points: 45,
            endgame_points: 20
        },
        scout: 'api_user'
    };

    try {
        const response = await axios.post(`${API_BASE}/scouting-data`, data, { headers });
        
        if (response.data.success) {
            console.log('Scouting data created successfully!');
        } else {
            console.error('Error:', response.data.error);
        }
    } catch (error) {
        console.error('Request failed:', error.message);
    }
}

getTeams();
createScoutingData();
```

### cURL

```bash
# Get team data
curl -H "Authorization: Bearer sk_live_your_api_key_here" \
     https://your-scout-domain.com/api/v1/teams

# Create scouting data
curl -X POST \
     -H "Authorization: Bearer sk_live_your_api_key_here" \
     -H "Content-Type: application/json" \
     -d '{
       "team_id": 1,
       "match_id": 1,
       "data": {
         "auto_points": 15,
         "teleop_points": 45,
         "endgame_points": 20
       },
       "scout": "api_user"
     }' \
     https://your-scout-domain.com/api/v1/scouting-data

# Trigger sync
curl -X POST \
     -H "Authorization: Bearer sk_live_your_api_key_here" \
     -H "Content-Type: application/json" \
     -d '{"type": "full"}' \
     https://your-scout-domain.com/api/v1/sync/trigger
```

## Best Practices

### Security

1. **Keep API keys secure**: Never commit API keys to version control
2. **Use environment variables**: Store API keys in environment variables
3. **Rotate keys regularly**: Create new keys and deactivate old ones periodically
4. **Use HTTPS**: Always use HTTPS for API requests
5. **Validate permissions**: Only grant necessary permissions to each key

### Performance

1. **Respect rate limits**: Monitor your usage and stay within limits
2. **Use pagination**: Use the `limit` parameter for large datasets
3. **Cache responses**: Cache API responses when appropriate
4. **Filter requests**: Use query parameters to get only needed data

### Error Handling

1. **Check response status**: Always check the `success` field
2. **Handle rate limits**: Implement exponential backoff for 429 errors
3. **Log errors**: Log API errors for debugging
4. **Validate data**: Validate request data before sending

### Development

1. **Test with low limits**: Use lower rate limits during development
2. **Use descriptive names**: Give API keys descriptive names
3. **Monitor usage**: Check API usage regularly in the web interface
4. **Document integrations**: Document your API integrations

## Troubleshooting

### Common Issues

**401 Unauthorized**
- Check your API key is correct
- Verify the key hasn't expired
- Ensure you're using the correct authentication method

**403 Forbidden**
- Check if your API key has the required permission
- Verify you're accessing data for your team

**429 Rate Limited**
- You've exceeded your hourly rate limit
- Wait for the limit to reset or request a higher limit

**404 Not Found**
- Check the endpoint URL is correct
- Verify the resource exists and belongs to your team

**422 Validation Error**
- Check your request data format
- Ensure required fields are provided
- Verify data types match the API specification

### Getting Help

1. Check the API logs in your Scout dashboard
2. Review your API key permissions and settings
3. Contact your team administrator for access issues
4. Check the Scout platform documentation for updates

## Changelog

### Version 1.0 (2025-09-16)
- Initial API release
- Team data access endpoints
- Scouting data CRUD operations
- Analytics endpoints
- Sync operations
- API key management system
- Rate limiting and usage tracking

---

This documentation is automatically updated. For the latest version, visit your Scout platform's API documentation page.