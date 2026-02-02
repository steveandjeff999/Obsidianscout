# Mobile API - Implementation Summary

## What Was Added

A comprehensive REST API has been added to OBSIDIAN Scout specifically designed for mobile applications. The API provides full access to scouting functionality via HTTP endpoints with JWT-based authentication.

## Key Features

###  Authentication
- **JWT Token-based authentication** - Secure, stateless authentication
- **7-day token expiration** - Long-lived tokens for mobile convenience
- **Token refresh endpoint** - Refresh tokens without re-login
- **Token verification** - Check token validity

###  Mobile-Optimized Design
- **RESTful endpoints** - Standard HTTP methods (GET, POST)
- **JSON responses** - Easy to parse in any language
- **Consistent error handling** - Predictable error format
- **Team isolation** - Data automatically scoped to user's team
- **Pagination support** - Efficient data loading

###  Year-Prefixed Event Codes
- **Automatic resolution** - Raw event codes (e.g., `OKTU`) auto-resolve to year-prefixed (e.g., `2026OKTU`)
- **Season-aware** - Uses team's configured season from `game_config.json`
- **Multi-year support** - Same event tracked separately across seasons (2025OKTU vs 2026OKTU)
- **Backwards compatible** - Falls back to raw codes for legacy data

###  Offline Sync Support
- **Bulk submission endpoint** - Upload multiple entries at once
- **Offline ID tracking** - Match server IDs to local data
- **Timestamp preservation** - Maintain accurate submission times
- **Individual result tracking** - Know which entries succeeded/failed

###  Complete Data Access
- **Teams** - List and details
- **Events** - Event information and schedules
- **Matches** - Match schedules and results
- **Scouting Data** - Submit and retrieve match scouting
- **Pit Scouting** - Submit pit scouting observations
- **Game Configuration** - Download current game config
- **Sync Status** - Check for updates

## Files Added

### 1. `app/routes/mobile_api.py`
The main API implementation with all endpoints:
- Authentication endpoints (login, refresh, verify)
- Team data endpoints
- Event endpoints
- Match endpoints
- Scouting data endpoints (submit, bulk-submit, history)
- Pit scouting endpoints
- Configuration endpoints
- Sync status endpoints
- Health check
- **Event code resolution helper** (`resolve_event_code_to_id`)

### 2. `MOBILE_API_DOCUMENTATION.md`
Complete API documentation including:
- All endpoint specifications
- Request/response examples
- Error handling guide
- Mobile app development guide
- Sample code (JavaScript, Swift)
- Best practices

### 3. `MOBILE_API_QUICKSTART.md`
Quick start guide with:
- Installation instructions
- Step-by-step testing guide
- Curl examples
- Postman setup
- Python testing script
- Troubleshooting tips

### 4. `test_mobile_api.py`
Automated test script that:
- Tests all major endpoints
- Validates authentication
- Checks data access
- Provides detailed output

## Files Modified

### 1. `app/__init__.py`
- Added mobile_api blueprint registration
- Integrated with existing Flask app

### 2. `requirements.txt`
- Added PyJWT>=2.8.0 for JWT token handling

## API Endpoint Structure

```
/api/mobile/
├── health                          [GET]    Health check
├── auth/
│   ├── login                       [POST]   Login and get token
│   ├── refresh                     [POST]   Refresh token
│   └── verify                      [GET]    Verify token validity
├── teams                           [GET]    List teams
├── teams/current                   [GET]    List teams for current event
├── teams/<id>                      [GET]    Team details
├── events                          [GET]    List events
├── matches                         [GET]    List matches
├── matches/current                 [GET]    List matches for current event
├── scouting/
│   ├── submit                      [POST]   Submit single entry
│   ├── bulk-submit                 [POST]   Submit multiple entries
│   └── history                     [GET]    User's scouting history
├── pit-scouting/
│   └── submit                      [POST]   Submit pit scouting
├── config/
│   └── game                        [GET]    Game configuration
└── sync/
    └── status                      [GET]    Sync status
```

## How to Use

### Step 1: Install Requirements
```bash
pip install -r requirements.txt
```

### Step 2: Start Server
```bash
python run.py
```

### Step 3: Test the API
```bash
python test_mobile_api.py
```

### Step 4: Read Documentation
- Full docs: `MOBILE_API_DOCUMENTATION.md`
- Quick start: `MOBILE_API_QUICKSTART.md`

## Authentication Flow

```
1. Mobile App → POST /api/mobile/auth/login
   ↓
2. Server validates credentials
   ↓
3. Server ← Returns JWT token
   ↓
4. Mobile App stores token securely
   ↓
5. Mobile App → Include "Authorization: Bearer <token>" in all requests
   ↓
6. Server validates token and processes request
```

## Example Usage

### JavaScript/React Native
```javascript
// Login option 1: username + team_number + password
const resp1 = await fetch('https://your-server:8080/api/mobile/auth/login', {
   method: 'POST',
   headers: { 'Content-Type': 'application/json' },
   body: JSON.stringify({ username: 'scout', team_number: 1234, password: 'pass' })
});
const { token: token1 } = await resp1.json();

// Login option 2: team_number + password (no username)
const resp2 = await fetch('https://your-server:8080/api/mobile/auth/login', {
   method: 'POST',
   headers: { 'Content-Type': 'application/json' },
   body: JSON.stringify({ team_number: 1234, password: 'pass' })
});
const { token: token2 } = await resp2.json();

// Use token (choose the token you received)
const teams = await fetch('https://your-server:8080/api/mobile/teams', {
   headers: { 'Authorization': `Bearer ${token1 || token2}` }
});
```

### Swift/iOS
```swift
// Login option 1: username + team_number + password
let body1 = ["username": "scout", "team_number": 1234, "password": "pass"]
var req1 = URLRequest(url: loginURL)
req1.httpMethod = "POST"
req1.httpBody = try JSONEncoder().encode(body1)
let (data1, _) = try await URLSession.shared.data(for: req1)
let loginResponse1 = try JSONDecoder().decode(LoginResponse.self, from: data1)

// Login option 2: team_number + password
let body2 = ["team_number": 1234, "password": "pass"]
var req2 = URLRequest(url: loginURL)
req2.httpMethod = "POST"
req2.httpBody = try JSONEncoder().encode(body2)
let (data2, _) = try await URLSession.shared.data(for: req2)
let loginResponse2 = try JSONDecoder().decode(LoginResponse.self, from: data2)

// Use token (choose the token you received)
var request = URLRequest(url: teamsURL)
request.setValue("Bearer \(loginResponse1.token ?? loginResponse2.token)", forHTTPHeaderField: "Authorization")
```

## Security Considerations

### Production Deployment

**️ IMPORTANT:** Before deploying to production, change the JWT secret key!

1. Open `app/routes/mobile_api.py`
2. Find `JWT_SECRET_KEY`
3. Replace with a secure random string:

```python
import secrets
JWT_SECRET_KEY = secrets.token_urlsafe(32)
```

Or use environment variable:
```python
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'fallback')
```

### Best Practices
- Always use HTTPS in production
- Store tokens securely (Keychain/KeyStore)
- Implement token refresh before expiration
- Handle token expiration gracefully
- Don't log or expose tokens

## Mobile App Development Tips

### Offline-First Architecture
1. **Queue submissions locally** when offline
2. **Sync when online** using bulk-submit endpoint
3. **Track sync status** with offline IDs
4. **Cache data** for offline viewing

### Data Management
1. **Cache teams/events** for quick access
2. **Update periodically** using sync status
3. **Handle conflicts** gracefully
4. **Show sync indicators** to users

### Error Handling
1. **Check success field** in all responses
2. **Parse error codes** for specific handling
3. **Implement retry logic** with exponential backoff
4. **Show user-friendly messages**

## Testing

### Manual Testing with curl
```bash
# Health check
curl http://localhost:8080/api/mobile/health

# Login
curl -X POST https://localhost:8080/api/mobile/auth/login -k \
   -H "Content-Type: application/json" \
   -d '{"username":"superadmin","team_number":1234,"password":"password"}'

# Or, login by team number only:
curl -X POST https://localhost:8080/api/mobile/auth/login -k \
   -H "Content-Type: application/json" \
   -d '{"team_number":1234,"password":"password"}'

# Get teams (with token)
curl http://localhost:8080/api/mobile/teams \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Automated Testing
```bash
python test_mobile_api.py
```

## Troubleshooting

### Common Issues

**"Module not found: jwt"**
- Solution: `pip install PyJWT`

**"Authentication token is missing"**
- Solution: Include Authorization header with Bearer token

**"Invalid or expired token"**
- Solution: Login again or use refresh endpoint

**"Team not found"**
- Solution: Ensure user has scouting_team_number assigned

## Integration with Existing Features

The Mobile API integrates seamlessly with existing OBSIDIAN Scout features:

-  **Team Isolation** - Uses existing team scoping
-  **User Authentication** - Leverages existing User model
-  **Data Models** - Uses same Team, Match, ScoutingData models
-  **Permissions** - Respects user roles
-  **Game Config** - Accesses same configuration system

## Performance Considerations

- **Pagination** - Limit query results to avoid large payloads
- **Caching** - Implement client-side caching
- **Compression** - Enable gzip compression on server
- **Background Sync** - Use background tasks for large syncs

## Future Enhancements

Potential additions for future versions:
- [ ] Push notifications via API
- [ ] Real-time updates via WebSocket
- [ ] Image upload for pit scouting
- [ ] Analytics endpoints
- [ ] Export functionality
- [ ] OAuth2 support
- [ ] Rate limiting
- [ ] API versioning

## Support

For questions or issues:
1. Check the documentation files
2. Review server logs for errors
3. Test with `test_mobile_api.py`
4. Verify authentication tokens
5. Check data exists for your team

## Summary

The Mobile API provides everything needed to build a fully-featured mobile scouting app:

 Secure authentication
 Complete data access
 Offline sync support
 Mobile-optimized design
 Comprehensive documentation
 Test scripts included
 Production-ready code

Start building your mobile app today! 
