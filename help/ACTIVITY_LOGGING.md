# Activity Logging System

## Overview

The Activity Logging System tracks all user interactions within the application, including keystrokes, button clicks, form submissions, and page navigation. This comprehensive logging provides administrators with full visibility into user actions for security, audit, and troubleshooting purposes.

## Features

- **Detailed Keystroke Logging**: Captures what keys are pressed by users (passwords are masked for security)
- **User Action Tracking**: Records clicks, form submissions, and page navigation
- **User Context**: Each log entry includes the user identity, timestamp, and IP address
- **Admin Dashboard**: View, filter, and search activity logs through an intuitive interface
- **Automatic Collection**: No user action required - all interactions are automatically logged

## Setup

1. **Run Database Migration**:
   ```
   python other/add_activity_log.py
   ```

2. **Install Required Dependencies**:
   ```
   pip install -r requirements.txt
   ```
   
3. **Restart the Application**:
   The logging system will automatically begin tracking user activity

## Accessing Activity Logs

1. Log in with an administrator account
2. Click on your profile icon in the top-right corner
3. Select "Activity Logs" from the dropdown menu
4. Use the filters to narrow down results by user, action type, date range, or page

## Security Considerations

- Activity logs contain sensitive information and should only be accessible to administrators
- Password fields are automatically masked to prevent credential exposure
- The system complies with privacy regulations by clearly informing users that their actions are being logged

## Maintenance

- Logs may accumulate quickly in active systems
- Consider implementing a log rotation/archival strategy for long-term use
- Regularly backup the activity log database table

## Troubleshooting

If logging is not working correctly:

1. Check that the activity_log table exists in the database
2. Verify that the activity-logger.js file is being loaded in the browser (check browser console)
3. Ensure the activity route is registered in the Flask application

For any issues, please contact the system administrator.
