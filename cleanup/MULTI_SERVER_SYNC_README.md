# Multi-Server Synchronization System

## Overview

The Multi-Server Synchronization System allows multiple scouting servers to automatically sync their data, instance files, configuration, and uploads in real-time. This enables you to run multiple servers at different locations while keeping all data synchronized without any authentication requirements - servers communicate using IP addresses or domain names.

## Features

###  **Real-Time Synchronization**
- **Instant sync** when files or database changes are detected
- **Automatic periodic sync** at configurable intervals (default: 30 seconds)
- **File monitoring** with change detection (default: 5 second intervals)
- **Real-time status updates** via WebSocket connections

###  **No Authentication Required**
- **IP-based communication** - no API keys or passwords needed
- **Domain name support** - use hostnames or IP addresses
- **Zero-configuration networking** - works out of the box on local networks
- **Secure HTTPS support** - optional SSL/TLS encryption

###  **Comprehensive Data Sync**
- **Database synchronization** - all scouting data, teams, matches, events
- **Instance files** - database files, logs, and instance folder contents
- **Configuration files** - game config, themes, and application settings
- **Upload files** - images, documents, and user uploads
- **Selective sync** - enable/disable specific sync types per server

###  **Superadmin Management**
- **Web-based interface** for managing sync servers
- **Real-time monitoring** of server health and sync status
- **Manual sync triggers** for immediate synchronization
- **Detailed logging** of all sync operations
- **Error tracking** with automatic retry mechanisms

## Quick Setup Guide

### 1. Run the Migration Script
First, set up the sync database tables:

```powershell
python setup_multi_server_sync.py
```

### 2. Access the Sync Dashboard
1. Log in as **superadmin** (username: `superadmin`, password: `password`)
2. Go to **Multi-Server Sync** in the navigation menu
3. You'll see the sync dashboard with current status

### 3. Add Your First Sync Server
1. Click **"Manage Servers"** from the dashboard
2. Click **"Add Server"** 
3. Fill in the server details:
   - **Name**: A friendly name (e.g., "Competition Server")
   - **Host**: IP address (e.g., `192.168.1.100`) or domain (e.g., `scout.team5454.org`)
   - **Port**: Usually `5000` (the default Flask port)
   - **Protocol**: Choose `HTTPS` (recommended) or `HTTP`
4. Configure what to sync (all enabled by default):
   -  Database Synchronization
   -  Instance Files
   -  Configuration Files 
   -  Uploaded Files
5. Click **"Add Server"**

### 4. Verify Connection
- The system will automatically test the connection
- Check the server status in the **"Manage Servers"** page
- Look for a **green "Healthy"** status badge

### 5. Monitor Sync Activity
- View real-time sync status on the dashboard
- Check recent sync activity in the logs
- Monitor server health and error counts

## Server Requirements

Each server in your sync network must:

1. **Run the same version** of the scouting application
2. **Have network connectivity** to other servers
3. **Be accessible** on the configured port (default: 5000)
4. **Have the sync system enabled** (enabled by default)

## Network Configuration

### Local Network Setup
For servers on the same local network:
- Use private IP addresses (e.g., `192.168.1.100`, `10.0.0.50`)
- Ensure servers can reach each other on port 5000
- No firewall configuration needed for local networks

### Internet/WAN Setup
For servers across the internet:
- Use public IP addresses or domain names
- Configure port forwarding on routers (port 5000)
- Consider using HTTPS for security
- Ensure firewall allows incoming connections on port 5000

### Competition Setup Example
```
Main Server (192.168.1.10)
├── Scout Station 1 (192.168.1.11)
├── Scout Station 2 (192.168.1.12)
├── Scout Station 3 (192.168.1.13)
└── Backup Server (192.168.1.20)
```

## Configuration Options

### Global Sync Settings
Access via **Multi-Server Sync** → **Settings**:

- **Enable Automatic Synchronization**: Turn sync on/off globally
- **Sync Interval**: How often to sync (10-3600 seconds, default: 30)
- **File Watch Interval**: How often to check for file changes (1-300 seconds, default: 5)

### Per-Server Settings
Configure for each server individually:

- **Sync Priority**: Higher numbers = higher priority (1 = highest)
- **Database Sync**: Enable/disable database synchronization
- **Instance Files**: Enable/disable instance folder sync
- **Config Files**: Enable/disable configuration file sync
- **Uploads**: Enable/disable uploaded file sync
- **Connection Timeout**: How long to wait for responses (default: 30 seconds)
- **Retry Attempts**: How many times to retry failed operations (default: 3)

## API Endpoints

The system provides RESTful API endpoints for server-to-server communication:

### Health Check
```
GET /api/sync/ping
```
Returns server status and version information.

### File Operations
```
GET /api/sync/files/checksums?path=instance
POST /api/sync/files/upload
GET /api/sync/files/download?path=file.txt&base_folder=instance
```

### Database Sync
```
POST /api/sync/database
GET /api/sync/database/changes?since=2024-01-01T00:00:00
```

### Server Management
```
GET /api/sync/servers
POST /api/sync/servers
DELETE /api/sync/servers/{id}
POST /api/sync/servers/{id}/sync
```

## Monitoring and Troubleshooting

### Dashboard Monitoring
- **Server Status**: Green = healthy, Red = error, Yellow = warning
- **Last Sync**: Timestamp of last successful sync
- **Error Count**: Number of consecutive errors
- **Sync Progress**: Real-time progress for active syncs

### Log Analysis
Check the **"View Logs"** page for:
- Sync operation history
- Error messages and stack traces
- Performance metrics (duration, items synced)
- Network connectivity issues

### Common Issues

#### "Server not responding"
- Check network connectivity: `ping [server-ip]`
- Verify the server is running: check if you can access it in a browser
- Confirm firewall settings allow port 5000
- Test connection using the built-in connection test

#### "Sync taking too long"
- Large file uploads may take time - check the progress
- Network bandwidth limitations
- Increase connection timeout in server settings
- Consider reducing sync frequency for large datasets

#### "Database conflicts"
- The system uses checksums to detect conflicts
- Manual resolution may be needed for complex conflicts
- Check the sync logs for detailed conflict information

### Manual Sync Options
- **Sync All Servers**: Sync with all configured servers immediately
- **Force Full Sync**: Complete sync ignoring timestamps
- **Server-Specific Sync**: Sync with just one server
- **Type-Specific Sync**: Sync only database, files, or config

## Security Considerations

### Network Security
- Use HTTPS when possible (especially over the internet)
- Limit network access to trusted servers only
- Consider VPN for servers across the internet
- Monitor sync logs for unauthorized access attempts

### Data Security
- All synced data maintains the same access controls
- User authentication is handled per-server (not synced)
- File integrity checks prevent corruption
- Backup data before major sync operations

### Access Control
- Only **superadmin** users can manage sync servers
- Sync configuration changes are logged
- Server removal requires confirmation
- Emergency stop available via global sync disable

## Performance Optimization

### For Large Datasets
- Increase sync intervals during heavy usage
- Use selective sync (disable unnecessary sync types)
- Perform major syncs during off-peak hours
- Monitor network bandwidth usage

### For Many Servers
- Use sync priorities to control order
- Stagger sync times to reduce network load
- Consider using a hub-and-spoke topology
- Monitor server performance metrics

### Network Optimization
- Use wired connections when possible
- Ensure adequate bandwidth for all servers
- Position servers geographically for best connectivity
- Use local file servers for large uploads

## Backup and Recovery

### Automatic Backups
- Database backups are created before major syncs
- File checksums prevent corruption
- Sync logs provide operation history
- Failed operations are automatically retried

### Manual Backup
Before adding new servers or making major changes:
1. Stop sync services temporarily
2. Backup the instance folder
3. Export database to SQL file
4. Save current configuration files

### Recovery Process
If sync corruption occurs:
1. Disable sync on all servers
2. Identify the server with correct data
3. Restore other servers from backup
4. Re-enable sync and force full sync

## Advanced Features

### Primary Server Designation
- Mark one server as "primary" for conflict resolution
- Primary server's data takes precedence in conflicts
- Useful for hub-and-spoke configurations

### Custom Sync Schedules
- Different sync intervals per server
- Priority-based sync ordering
- Conditional sync based on server status

### Real-Time Notifications
- WebSocket updates for sync status
- Toast notifications for completed operations
- Email alerts for critical errors (future feature)

## API Integration

### Adding Servers Programmatically
```bash
curl -X POST http://localhost:5000/api/sync/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "New Server",
    "host": "192.168.1.50",
    "port": 5000,
    "protocol": "https"
  }'
```

### Triggering Manual Sync
```bash
curl -X POST http://localhost:5000/api/sync/servers/1/sync \
  -H "Content-Type: application/json" \
  -d '{"sync_type": "full"}'
```

### Getting Sync Status
```bash
curl http://localhost:5000/api/sync/status
```

## Troubleshooting Guide

### Connection Issues
1. **Test basic connectivity**: Try accessing `http://[server-ip]:5000` in a browser
2. **Check firewall**: Ensure port 5000 is open
3. **Verify SSL certificates**: For HTTPS, ensure valid certificates
4. **Network routing**: Confirm servers can reach each other

### Sync Failures
1. **Check error logs**: Look in the sync logs for specific error messages
2. **Verify disk space**: Ensure sufficient space on all servers
3. **Database permissions**: Confirm write access to database files
4. **File permissions**: Check read/write access to instance and config folders

### Performance Issues
1. **Monitor resource usage**: Check CPU, memory, and disk I/O
2. **Network bandwidth**: Ensure adequate speed for data transfer
3. **Sync intervals**: Reduce frequency if servers are overwhelmed
4. **Selective sync**: Disable unused sync types

## Future Enhancements

### Planned Features
- **Conflict resolution UI**: Manual resolution for complex conflicts
- **Sync scheduling**: Time-based sync schedules
- **Email notifications**: Alerts for sync failures
- **Bandwidth throttling**: Rate limiting for large transfers
- **Compression**: Reduce network usage for large files
- **Encryption**: End-to-end encryption for sensitive data

### Community Contributions
We welcome contributions to improve the sync system:
- Bug reports and feature requests
- Code contributions and pull requests
- Documentation improvements
- Testing and feedback from real competitions

## Support

### Getting Help
- Check this documentation first
- Review the sync logs for error details
- Test with a simple two-server setup
- Report issues with detailed error messages

### Best Practices
- Start with a simple setup and expand gradually
- Test thoroughly before competitions
- Keep servers on the same software version
- Monitor sync status regularly
- Have a backup plan for network failures

---

** Ready to sync? Start by running `python setup_multi_server_sync.py` and adding your first server!**
