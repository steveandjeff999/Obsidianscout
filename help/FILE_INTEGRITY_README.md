# File Integrity Monitoring System

## Overview

The File Integrity Monitoring System is a security feature that monitors all application files for unauthorized changes. When files are modified, the system requires authentication before allowing continued access to the application.

## Features

- **Startup Integrity Check**: Checks all application files at server startup
- **Checksum Verification**: Uses SHA256 checksums to detect file changes
- **Warning-Only Mode**: Option to only show warnings without blocking access
- **Password Protection**: Requires a password to reset integrity monitoring after compromise
- **Server Shutdown**: Automatically shuts down the server if incorrect password is provided (security mode only)
- **Selective Monitoring**: Excludes configuration files, logs, and temporary files
- **Web Interface**: Easy-to-use admin interface for configuration

## How It Works

1. **Initialization**: On startup, the system calculates checksums for all monitored files
2. **Startup Check**: Files are checked once at application startup
3. **Compromise Detection**: If any file changes are detected, the system marks integrity as compromised
4. **Access Control**: All requests are redirected to a verification page when integrity is compromised
5. **Password Verification**: Users must enter the correct integrity password to continue
6. **Reset or Shutdown**: Correct password resets monitoring; incorrect password shuts down server

## File Exclusions

The following files and directories are NOT monitored:
- `__pycache__/` directories and `.pyc` files
- `game_config.json` and `ai_config.json` (configuration files)
- `scouting.db` (database file)
- `uploads/` directory
- `ssl/` directory and certificates
- Log files (`.log`)
- Temporary files (`.tmp`)
- Git files (`.git`)
- Integrity system files (`file_checksums.json`, `integrity_config.json`)

## Configuration

### Default Settings
- **Default Password**: `admin123`
- **Checking Time**: At application startup
- **Checksum Algorithm**: SHA256
- **Security Mode**: Warning-only mode disabled (security mode enabled)

### Operating Modes

#### Security Mode (Default)
- File changes trigger password authentication
- Incorrect password shuts down server
- Users redirected to verification page

#### Warning-Only Mode
- File changes only show console warnings
- No password authentication required
- Application remains accessible
- Useful for development environments

### Accessing Configuration
1. Navigate to the Admin Settings page (requires admin privileges)
2. Click "Integrity Settings" button under the File Integrity card
3. All integrity configuration is restricted to admin users only

### Updating Password
1. Go to File Integrity configuration page
2. Enter new password (minimum 6 characters)
3. Confirm password
4. Click "Update Password"

### Switching Modes
1. Go to File Integrity configuration page
2. Toggle "Warning-Only Mode" checkbox
3. Click "Update Mode"

## Usage Scenarios

### Normal Operation
- System runs normally with background monitoring
- No user interaction required
- Files are checked every 30 seconds

### File Integrity Compromised
1. System detects file changes
2. All requests redirect to verification page
3. User must enter integrity password
4. Correct password: resets monitoring and continues
5. Incorrect password: server shuts down for security

### Administrative Actions
- **Reinitialize**: Recalculate checksums (use after legitimate updates)
- **Update Password**: Change the integrity password
- **View Status**: Check monitoring status and statistics

## Security Considerations

### Threats Mitigated
- Unauthorized code modifications
- Malicious file tampering
- Accidental file corruption
- Backdoor installations

### Limitations
- Does not protect against runtime attacks
- Cannot detect changes to excluded files
- Requires manual reinitialization after legitimate updates

## Troubleshooting

### Common Issues

**Issue**: Integrity compromised on startup
**Solution**: Files may have been legitimately modified. Use "Reinitialize" in config.

**Issue**: Forgot integrity password
**Solution**: Check `instance/integrity_config.json` or reset database.

**Issue**: Too many false positives
**Solution**: Check if development tools are modifying files automatically.

### Reset Procedures

**Emergency Reset** (if locked out):
1. Stop the server
2. Delete `instance/file_checksums.json`
3. Delete `instance/integrity_config.json`
4. Restart server (will use default password)

**Clean Reset**:
1. Use "Reinitialize" button in admin interface
2. System will recalculate all checksums

## Technical Details

### File Structure
```
instance/
├── file_checksums.json     # Stored checksums
├── integrity_config.json   # Password hash
└── scouting.db            # Main database
```

### Checksum Format
```json
{
  "checksums": {
    "app/models.py": {
      "checksum": "sha256_hash_here",
      "modified": 1234567890.123,
      "size": 1024
    }
  },
  "created": "2025-01-01T12:00:00"
}
```

### API Endpoints
- `GET /integrity/verify` - Verification page
- `POST /integrity/verify` - Submit password
- `GET /integrity/status` - Monitoring status (login required)
- `GET /auth/admin/integrity` - Admin configuration (admin only)
- `POST /auth/admin/integrity/password` - Update password (admin only)
- `POST /auth/admin/integrity/mode` - Toggle warning mode (admin only)
- `POST /auth/admin/integrity/reinitialize` - Reset monitoring (admin only)

## Best Practices

1. **Change Default Password**: Always change from `admin123` in production
2. **Regular Reinitialization**: Reinitialize after legitimate updates
3. **Monitor Logs**: Check console output for integrity events
4. **Backup Configurations**: Keep backup of integrity settings
5. **Test Procedures**: Regularly test integrity and recovery procedures

## Development Notes

- System is designed to be lightweight and non-intrusive
- Monitoring runs in background thread
- Password hashing uses Werkzeug's secure methods
- Thread-safe implementation for concurrent access
- Graceful shutdown handling

## Future Enhancements

- Email notifications on integrity compromise
- Multiple administrator passwords
- File-specific monitoring rules
- Integration with external security systems
- Audit logging of integrity events

## Security Best Practices

- Use strong, unique passwords for your account.
- Log out when finished using the app.
- Do not share your login credentials.
- Report suspicious activity to your admin immediately.
