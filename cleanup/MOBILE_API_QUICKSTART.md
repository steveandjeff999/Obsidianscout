# Mobile API Quick Start Guide

This guide will help you quickly test the Mobile API endpoints using curl, Postman, or any HTTP client.

## Prerequisites

1. OBSIDIAN Scout server is running
2. You have a user account created (username and password)
3. Your user has a `scouting_team_number` assigned

## Step 1: Install PyJWT

The mobile API requires the PyJWT library for JWT token authentication.

```bash
pip install PyJWT>=2.8.0
```

Or install from requirements.txt:

### Register a New Account (Mobile)

Create a new account scoped to a team. If you run into `ACCOUNT_CREATION_LOCKED` ask your team's administrator to unlock account creation.

```bash
curl -X POST https://localhost:8080/api/mobile/auth/register -k \
  -H "Content-Type: application/json" \
  -d '{"username":"new_scout","password":"Pa55word!","confirm_password":"Pa55word!","team_number":5454,"email":"new@scout.example"}'
```

Expected response (201):

```json
{
  "success": true,
  "token": "eyJ...",
  "user": {"id": 123, "username": "new_scout", "team_number": 5454, "roles": ["scout"]},
  "expires_at": "2025-01-01T00:00:00Z"
}
```

```bash
pip install -r requirements.txt
```

## Step 2: Start the Server

Make sure your OBSIDIAN Scout server is running:

```bash
python run.py
```

The server should start on `https://localhost:8080` (or your configured port). For local development the server may use a self-signed certificate — see notes below on how to call the API in that case.

## Step 3: Test the API

### Health Check (No Authentication Required)

```bash
curl -k https://localhost:8080/api/mobile/health
```

Expected response:
```json
{
  "success": true,
  "status": "healthy",
  "version": "1.0",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### Login and Get Token

Replace `USERNAME`, `TEAM_NUMBER` and `PASSWORD` with your actual credentials. The mobile API supports two login forms:

1) username + team_number + password

```bash
curl -X POST https://localhost:8080/api/mobile/auth/login -k \
  -H "Content-Type: application/json" \
  -d '{"username":"USERNAME","team_number":TEAM_NUMBER,"password":"PASSWORD"}'
```

2) team_number + password (no username)

```bash
curl -X POST https://localhost:8080/api/mobile/auth/login -k \
  -H "Content-Type: application/json" \
  -d '{"team_number":TEAM_NUMBER,"password":"PASSWORD"}'
```

Expected response:
```json
{
  "success": true,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 1,
    "username": "USERNAME",
    "team_number": 5454,
    "roles": ["scout"]
  },
  "expires_at": "2024-01-08T12:00:00Z"
}
```

**Save the token** - you'll need it for subsequent requests!

### Get Teams (Requires Authentication)

Replace `YOUR_TOKEN` with the token from the login response (use `-k` with curl for self-signed certs):

```bash
curl -k https://localhost:8080/api/mobile/teams \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Get Events

```bash
curl -k https://localhost:8080/api/mobile/events \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Get Matches for an Event

Replace `EVENT_ID` with an actual event ID:

```bash
curl -k "https://localhost:8080/api/mobile/matches?event_id=EVENT_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Submit Scouting Data

Replace placeholders with actual values:

```bash
curl -k -X POST https://localhost:8080/api/mobile/scouting/submit \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": 1,
    "match_id": 1,
    "data": {
      "auto_speaker_scored": 3,
      "auto_amp_scored": 2,
      "teleop_speaker_scored": 10,
      "notes": "Great performance!"
    },
    "offline_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

### Get Game Configuration

```bash
curl -k https://localhost:8080/api/mobile/config/game \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Testing with Postman

1. **Create a new Collection** named "OBSIDIAN Scout Mobile API"

2. **Add Environment Variables:**
   - `base_url`: `http://localhost:8080`
   - `token`: (leave empty, will be set after login)

3. **Create Login Request:**
   - Method: POST
   - URL: `{{base_url}}/api/mobile/auth/login`
   - Body (JSON):
     ```json
     {
       "username": "your_username",
       "password": "your_password"
     }
     ```
   - In Tests tab, add:
     ```javascript
     if (pm.response.code === 200) {
       var jsonData = pm.response.json();
       pm.environment.set("token", jsonData.token);
     }
     ```

4. **Create Authenticated Request Template:**
   - Add header: `Authorization: Bearer {{token}}`
   - Use for all other endpoints

## Testing with Python

```python
import requests
import json

# Base URL
BASE_URL = "https://localhost:8080/api/mobile"

# Login
login_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={
      # Option A: username + team_number + password
      "username": "your_username",
      "team_number": 1234,
      "password": "your_password"
      # Or Option B: team_number + password (omit username)
      # "team_number": 1234,
      # "password": "your_password"
    },
    verify=False  # disable SSL verification for local self-signed certs
)

if login_response.status_code == 200:
    data = login_response.json()
    token = data["token"]
    print(f"Login successful! Token: {token[:20]}...")
    
    # Use token for authenticated requests
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Get teams
    teams_response = requests.get(f"{BASE_URL}/teams", headers=headers)
    print(f"Teams: {teams_response.json()}")
    
    # Get events
    events_response = requests.get(f"{BASE_URL}/events", headers=headers)
    print(f"Events: {events_response.json()}")
    
    # Submit scouting data
    scouting_response = requests.post(
        f"{BASE_URL}/scouting/submit",
        headers=headers,
        json={
            "team_id": 1,
            "match_id": 1,
            "data": {
                "auto_speaker_scored": 3,
                "notes": "Test submission"
            },
            "offline_id": "test-uuid-123"
        }
    )
    print(f"Scouting submission: {scouting_response.json()}")
else:
    print(f"Login failed: {login_response.json()}")
```

## Common Issues

### 1. "Module not found: jwt"

**Solution:** Install PyJWT
```bash
pip install PyJWT
```

### 2. "Authentication token is missing"

**Solution:** Make sure to include the Authorization header:
```bash
-H "Authorization: Bearer YOUR_TOKEN"
```

### 3. "Invalid or expired token"

**Solution:** Login again to get a fresh token. Tokens expire after 7 days.

### 4. "User not found or inactive"

**Solution:** Check that:
- Your user account exists in the database
- The account is active (`is_active = True`)
- The user has a `scouting_team_number` assigned

### 5. "Team not found or not accessible"

**Solution:** Data is filtered by scouting team. Make sure:
- Teams exist for your scouting team number
- You're using correct team/match/event IDs
- Your user's `scouting_team_number` matches the data you're trying to access

## Security Configuration

**Important:** The current JWT secret key is a placeholder. For production use, you should:

1. Open `app/routes/mobile_api.py`
2. Change the `JWT_SECRET_KEY` to a secure random string:

```python
# Generate a secure secret key:
import secrets
print(secrets.token_urlsafe(32))

# Then update in mobile_api.py:
JWT_SECRET_KEY = 'your-secure-random-key-here'
```

Or better yet, move it to environment variables:

```python
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'fallback-key')
```

## Next Steps

1. Read the full [Mobile API Documentation](MOBILE_API_DOCUMENTATION.md)
2. Build your mobile app using the API
3. Implement offline sync for better user experience
4. Add error handling and retry logic
5. Implement token refresh to avoid re-login

## API Endpoints Summary

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| `/api/mobile/health` | GET | No | Health check |
| `/api/mobile/auth/login` | POST | No | Login and get token |
| `/api/mobile/auth/refresh` | POST | Yes | Refresh token |
| `/api/mobile/auth/verify` | GET | Yes | Verify token |
| `/api/mobile/teams` | GET | Yes | Get teams list |
| `/api/mobile/teams/<id>` | GET | Yes | Get team details |
| `/api/mobile/events` | GET | Yes | Get events |
| `/api/mobile/matches` | GET | Yes | Get matches |
| `/api/mobile/scouting/submit` | POST | Yes | Submit scouting data |
| `/api/mobile/scouting/bulk-submit` | POST | Yes | Bulk submit (offline sync) |
| `/api/mobile/scouting/history` | GET | Yes | Get user's scouting history |
| `/api/mobile/pit-scouting/submit` | POST | Yes | Submit pit scouting |
| `/api/mobile/config/game` | GET | Yes | Get game configuration |
| `/api/mobile/sync/status` | GET | Yes | Get sync status |

## Support

For issues or questions:
1. Check server logs for detailed error messages
2. Verify your authentication token is valid
3. Ensure all required fields are included in requests
4. Check the error code in the API response
5. Refer to the full documentation for details

Happy coding! 
