# Dual API Integration Documentation

## Overview

The FRC Scouting Platform now supports both the **FIRST API** (official) and **The Blue Alliance API** with automatic fallback functionality. This provides redundancy and ensures your scouting platform can continue to function even if one API is unavailable.

## Supported APIs

### 1. FIRST API (Official)
- **Base URL:** `https://frc-api.firstinspires.org`
- **Authentication:** Username + Auth Token (Basic Auth)
- **Coverage:** Official FRC events and data
- **Requires:** Registration with FIRST and API credentials

### 2. The Blue Alliance API
- **Base URL:** `https://www.thebluealliance.com/api/v3`
- **Authentication:** API Key (optional but recommended)
- **Coverage:** Comprehensive FRC data from 1992 to present
- **Requires:** TBA account for API key (optional)

## Features

### Automatic Fallback
- If the primary API fails, the system automatically tries the secondary API
- Transparent to the user - no manual intervention required
- Error handling and logging for troubleshooting

### Unified Data Format
- Both APIs return data in a standardized format for the database
- Consistent experience regardless of which API is used
- Automatic data conversion from API-specific formats

### Configuration Flexibility
- Choose which API to use as primary
- Configure credentials for both APIs
- Test both APIs independently

## Setup Instructions

### 1. FIRST API Setup
1. Visit the FIRST API portal
2. Create an account and request API access
3. Obtain your username and authorization token
4. In the scouting platform, go to **Configuration > API Settings**
5. Enter your FIRST API credentials

### 2. The Blue Alliance API Setup
1. Visit [thebluealliance.com/account](https://www.thebluealliance.com/account)
2. Create an account or log in
3. Navigate to the "Read API Keys" section
4. Generate a new API key
5. In the scouting platform, go to **Configuration > API Settings**
6. Enter your TBA API key

**Note:** TBA API works without authentication for basic usage, but an API key provides better rate limits and access to additional features.

### 3. Configure Preferred API Source
1. Go to **Configuration > API Settings**
2. Select your preferred API source:
   - **FIRST API**: Use official FIRST data as primary
   - **The Blue Alliance API**: Use TBA data as primary
3. The system will automatically fall back to the other API if the primary fails

## API Testing

A built-in testing interface is available to verify your API configuration:

1. **Access:** Admin menu > API Testing (admin users only)
2. **Features:**
   - View API configuration status
   - Test both APIs with real event data
   - Quick test with sample event codes
   - Manual testing for specific endpoints

### Testing Workflow
1. Configure your API credentials
2. Access the API Testing interface
3. Run a quick test with a known event code (e.g., `2024cala`)
4. Verify both APIs are working correctly
5. Check fallback functionality by temporarily disabling one API

## Event Code Formats

### FIRST API
- Uses simple event codes: `CALA`, `NYRO`, `TXDAL`
- Case-insensitive
- Typically 4-5 characters

### The Blue Alliance API
- Uses year-prefixed codes: `2024cala`, `2024nyro`, `2024txdal`
- Must be lowercase
- Format: `{year}{event_code}`

The system automatically handles the conversion between formats.

## Configuration Examples

### Game Configuration (game_config.json)
```json
{
  "preferred_api_source": "tba",
  "api_settings": {
    "username": "your_username",
    "auth_token": "your_auth_token",
    "base_url": "https://frc-api.firstinspires.org"
  },
  "tba_api_settings": {
    "auth_key": "your_tba_api_key",
    "base_url": "https://www.thebluealliance.com/api/v3"
  }
}
```

### Environment Variables (Optional)
```bash
FRC_API_KEY=your_first_api_token
TBA_API_KEY=your_tba_api_key
```

## API Usage in Code

### Teams Sync
```python
from app.utils.api_utils import get_teams_dual_api

# Get teams for an event using dual API
teams = get_teams_dual_api('CALA')  # Automatically handles both APIs
```

### Matches Sync
```python
from app.utils.api_utils import get_matches_dual_api

# Get matches for an event using dual API
matches = get_matches_dual_api('CALA')  # Automatically handles both APIs
```

### Event Details
```python
from app.utils.api_utils import get_event_details_dual_api

# Get event details using dual API
event_details = get_event_details_dual_api('CALA')
```

## Data Conversion

The system automatically converts data from both APIs to a standardized database format:

### Team Data
```python
{
    'team_number': 254,
    'team_name': 'The Cheesy Poofs',
    'location': 'San Jose, CA, USA'
}
```

### Match Data
```python
{
    'event_id': 1,
    'match_number': 1,
    'match_type': 'Qualification',
    'red_alliance': ['254', '1114', '469'],
    'blue_alliance': ['148', '2056', '971'],
    'red_score': 150,
    'blue_score': 120,
    'winner': 'red'
}
```

### Event Data
```python
{
    'name': 'Los Angeles Regional',
    'code': 'CALA',
    'year': 2024,
    'location': 'Los Angeles, CA, USA',
    'start_date': '2024-03-07',
    'end_date': '2024-03-10'
}
```

## Error Handling

### Primary API Failure
- System logs the primary API failure
- Automatically attempts the fallback API
- User sees transparent operation with success message

### Both APIs Fail
- Clear error message indicating both APIs are unavailable
- Detailed error information for troubleshooting
- Suggestion to check API configuration and network connectivity

### Common Error Scenarios
1. **Invalid API credentials:** Check username/token/API key
2. **Network connectivity issues:** Verify internet connection
3. **Invalid event codes:** Ensure event code format is correct
4. **API rate limiting:** TBA API key recommended for higher limits
5. **Event not found:** Verify event exists and code is correct

## Rate Limiting

### FIRST API
- Rate limits vary based on your agreement with FIRST
- Typically more restrictive than TBA

### The Blue Alliance API
- **Without API key:** 1 request per second
- **With API key:** Higher rate limits (varies by key type)
- Implements caching headers for efficiency

## Best Practices

1. **Configure both APIs** for maximum reliability
2. **Use TBA as primary** for most use cases (better rate limits, more comprehensive data)
3. **Keep FIRST API as fallback** for official event verification
4. **Test regularly** using the API testing interface
5. **Monitor logs** for API failures and errors
6. **Update API keys** before they expire

## Troubleshooting

### Common Issues

#### "Both APIs failed" Error
1. Check internet connectivity
2. Verify API credentials are correct
3. Test with known event codes (e.g., `2024cala`)
4. Check API testing interface for detailed errors

#### Teams/Matches Not Loading
1. Verify event code format is correct
2. Check if event exists on both APIs
3. Test individual APIs in the testing interface
4. Review application logs for detailed error messages

#### Configuration Not Saving
1. Ensure you have admin privileges
2. Check that all required fields are filled
3. Verify JSON syntax if editing configuration files directly
4. Check file permissions on configuration directory

### Debug Mode
Enable debug logging in `run.py` to see detailed API request/response information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## API Endpoint Reference

### The Blue Alliance API v3

#### Teams at Event
- **Endpoint:** `/event/{event_key}/teams`
- **Example:** `/event/2024cala/teams`

#### Event Matches
- **Endpoint:** `/event/{event_key}/matches`
- **Example:** `/event/2024cala/matches`

#### Event Details
- **Endpoint:** `/event/{event_key}`
- **Example:** `/event/2024cala`

### FIRST API v2.0

#### Teams at Event
- **Endpoint:** `/v2.0/{season}/teams/event/{event_code}`
- **Example:** `/v2.0/2024/teams/event/CALA`

#### Event Matches
- **Endpoint:** `/v2.0/{season}/schedule/{event_code}`
- **Example:** `/v2.0/2024/schedule/CALA`

#### Event Details
- **Endpoint:** `/v2.0/{season}/events?eventCode={event_code}`
- **Example:** `/v2.0/2024/events?eventCode=CALA`

## Support and Updates

### Getting Help
1. Use the API testing interface to diagnose issues
2. Check application logs for detailed error messages
3. Verify API credentials and event codes
4. Test with known working event codes

### Future Enhancements
- Additional API sources (if available)
- Enhanced caching for better performance
- Real-time API status monitoring
- Automatic API key rotation

---

For technical support or questions about API integration, please refer to the troubleshooting section above or check the application logs for detailed error information.
