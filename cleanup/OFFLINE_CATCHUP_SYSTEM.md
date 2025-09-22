# Offline Server Catch-up Synchronization System

## Overview

The Offline Server Catch-up Synchronization System automatically detects servers that have been offline and helps them catch up on missed database changes and file modifications when they come back online. This ensures that all servers in your multi-server scouting network stay synchronized even when some servers experience downtime.

## Features

### 🔍 **Smart Data-based Detection**
- Monitors database changes to detect servers missing latest data
- Compares server last sync timestamp with latest database changes
- No arbitrary time thresholds - only syncs when actually needed
- Counts exact number of missing changes per server

### 📊 **Database Change Catch-up**
- Leverages existing change tracking system to identify missed changes
- Batch processing for efficient large-scale synchronization
- Supports all CRUD operations (Create, Read, Update, Delete)
- Handles soft deletes and reactivations

### 📁 **File Synchronization**
- Timestamp-based file change detection
- Supports instance files, config files, and uploads
- Checksum verification for file integrity
- Incremental sync (only changed files)

### ⚡ **Performance Optimized**
- Configurable batch sizes for memory management
- Extended timeouts for large catch-up operations
- Retry logic with exponential backoff
- Background processing to avoid blocking

### 🛡️ **Robust Error Handling**
- Comprehensive logging and monitoring
- Graceful failure handling
- Transaction rollback on errors
- Detailed error reporting

## Architecture

### Core Components

1. **CatchupSyncManager** (`app/utils/catchup_sync.py`)
   - Main catch-up synchronization logic
   - Server detection and availability checking
   - Database and file synchronization coordination

2. **CatchupSyncScheduler** (`app/utils/catchup_scheduler.py`)
   - Background task scheduler
   - Automatic periodic catch-up scans
   - Configurable check intervals

3. **Enhanced Sync API** (`app/routes/sync_api.py`)
   - Catch-up specific API endpoints
   - Enhanced file checksums with timestamp filtering
   - Bulk change synchronization support

4. **Database Change Tracking** (`app/models/server_sync.py`)
   - Tracks all database modifications
   - Provides historical change data
   - Supports timestamp-based queries

## Configuration

### Environment Variables

```python
# In app configuration or SyncConfig table
CATCHUP_ENABLED = True                    # Enable/disable catch-up system
MAX_CATCHUP_DAYS = 30                    # Maximum days to look back for changes
CATCHUP_BATCH_SIZE = 100                 # Number of changes per batch
CATCHUP_CHECK_INTERVAL = 300             # Check interval in seconds (5 minutes)
CATCHUP_CONNECTION_TIMEOUT = 60          # Extended timeout for catch-up operations
```

### Database Configuration

The system uses the existing `SyncConfig` table for persistent configuration:

```sql
INSERT INTO sync_config (key, value, value_type) VALUES 
('catchup_enabled', 'true', 'boolean'),
('max_catchup_days', '30', 'integer'),
('catchup_batch_size', '100', 'integer'),
('catchup_check_interval', '300', 'integer'),
('catchup_scheduler_enabled', 'true', 'boolean');
```

## API Endpoints

### GET `/api/sync/catchup/status`
Get current catch-up system status and offline servers.

**Response:**
```json
{
  "catchup_enabled": true,
  "max_catchup_days": 30,
  "servers_needing_catchup": [
    {
      "id": 1,
      "name": "Server 2",
      "host": "192.168.1.101",
      "last_sync": "2025-08-10T12:00:00Z",
      "last_ping": "2025-08-10T11:30:00Z",
      "ping_success": false
    }
  ],
  "recent_catchup_logs": [
    {
      "id": 123,
      "server_name": "Server 2",
      "operation": "catch-up sync",
      "status": "completed",
      "created_at": "2025-08-11T08:15:00Z",
      "details": "Applied 45 database changes, 12 files synced"
    }
  ],
  "timestamp": "2025-08-11T08:30:00Z"
}
```

### POST `/api/sync/catchup/scan`
Trigger an immediate catch-up scan for all offline servers.

**Response:**
```json
{
  "message": "Catch-up scan completed",
  "servers_processed": 2,
  "results": [
    {
      "server_id": 1,
      "server_name": "Server 2",
      "started_at": "2025-08-11T08:30:00Z",
      "completed_at": "2025-08-11T08:32:30Z",
      "success": true,
      "database_changes": {
        "sent": 23,
        "received": 45,
        "applied": 45
      },
      "file_changes": {
        "uploaded": 5,
        "downloaded": 12
      },
      "errors": [],
      "duration": 150.5
    }
  ],
  "timestamp": "2025-08-11T08:32:30Z"
}
```

### Enhanced File Checksums

The existing `/api/sync/files/checksums` endpoint now supports catch-up mode:

**Parameters:**
- `path`: Directory path (instance/config/uploads)
- `catchup_mode`: true/false
- `since`: ISO timestamp (only for catch-up mode)

## Usage Examples

### Manual Catch-up Trigger

```python
from app.utils.catchup_sync import catchup_sync_manager

# Check for servers needing catch-up
servers_needing_catchup = catchup_sync_manager.detect_servers_needing_catchup()
print(f"Found {len(servers_needing_catchup)} servers needing catch-up")

# Run catch-up for all servers missing data
results = catchup_sync_manager.run_automatic_catchup()
for result in results:
    if result['success']:
        print(f"✅ {result['server_name']}: {result['database_changes']['applied']} changes applied")
    else:
        print(f"❌ {result['server_name']}: {len(result['errors'])} errors")
```

### API Usage

```bash
# Check catch-up status
curl http://localhost:5000/api/sync/catchup/status

# Trigger manual catch-up scan
curl -X POST http://localhost:5000/api/sync/catchup/scan

# Get file checksums for catch-up (files modified since timestamp)
curl "http://localhost:5000/api/sync/files/checksums?path=instance&catchup_mode=true&since=2025-08-10T12:00:00Z"
```

## Monitoring and Logging

### Log Messages

The system provides detailed logging with emoji indicators:

```
🔍 Latest database change: 2025-08-11 09:15:30
📊 backup-server (192.168.1.101): Missing 12 changes since 2025-08-11 08:30:00 - Available for catch-up
🔍 Detected 1 servers needing catch-up
✅ Server backup-server is now available  
🚀 Starting catch-up sync for backup-server
📅 Server backup-server last synced: 2025-08-11 08:30:00
🗄️ Starting database catch-up for backup-server since 2025-08-11 08:30:00
📤 Found 12 local changes to send
📥 Received 8 database changes from backup-server
✅ Applied 8 database changes from backup-server
📁 Starting file catch-up for backup-server since 2025-08-11 08:30:00
📤 Uploaded 2 files, 📥 Downloaded 5 files
✅ Catch-up sync completed for backup-server in 45.20 seconds
```

### Sync Logs

All catch-up operations are logged in the `sync_logs` table:

```sql
SELECT 
    sl.created_at,
    s.name as server_name,
    sl.operation,
    sl.status,
    sl.details
FROM sync_logs sl
JOIN sync_servers s ON sl.server_id = s.id
WHERE sl.operation LIKE '%catch-up%'
ORDER BY sl.created_at DESC;
```

## Operational Scenarios

### 1. Server Missing Latest Data

When a server is missing recent database changes:

1. **Detection**: Scheduler detects server's last sync is before the latest database change
2. **Missing Change Count**: System counts exactly how many changes the server is missing
3. **Availability Check**: Ping the server to confirm it's accessible
4. **Catch-up Period**: Use the server's last sync time as the starting point (or 7 days for never-synced servers)
5. **Database Sync**: 
   - Get all local changes since the server's last sync
   - Send changes in batches to the server
   - Receive all remote changes from the server
   - Apply remote changes locally
6. **File Sync**:
   - Compare file checksums for modified files
   - Upload newer local files
   - Download newer remote files
7. **Completion**: Update server sync timestamp and log results

### 2. Server That Has Never Synced

For servers that have never synced before:

1. **Default Lookback**: Use a 7-day lookback period for initial sync
2. **Full Sync**: Sync all available changes within the lookback period
3. **Baseline Establishment**: Establish the server's initial sync baseline

### 3. Network Issues During Catch-up

The system handles temporary network issues:

1. **Retry Logic**: Automatic retries with exponential backoff
2. **Batch Processing**: Continue with next batch if one fails
3. **Partial Success**: Apply what can be synchronized
4. **Error Reporting**: Detailed error logs for troubleshooting

## Best Practices

### 1. Configuration Tuning

- **Batch Size**: Increase for fast networks, decrease for slow/unreliable connections
- **Check Interval**: More frequent for critical environments, less frequent for stable networks
- **Timeout Values**: Adjust based on typical catch-up volume and network speed

### 2. Monitoring

- Monitor catch-up logs regularly
- Set up alerts for repeated catch-up failures
- Track catch-up duration trends

### 3. Network Planning

- Ensure adequate bandwidth for catch-up operations
- Consider off-peak scheduling for large catch-ups
- Test catch-up procedures in staging environments

### 4. Data Integrity

- Verify critical data after large catch-up operations
- Consider checksums or data validation procedures
- Maintain backup procedures independent of sync system

## Troubleshooting

### Common Issues

1. **Server Not Detected as Offline**
   - Check server clock synchronization
   - Verify sync_enabled flag in database
   - Check network connectivity

2. **Catch-up Takes Too Long**
   - Increase batch size for better performance
   - Check network bandwidth and latency
   - Consider database indexing on timestamp fields

3. **Changes Not Applied**
   - Check error logs for specific failure reasons
   - Verify database permissions and constraints
   - Check for data conflicts or validation errors

4. **File Sync Issues**
   - Verify file permissions and disk space
   - Check excluded file patterns
   - Ensure directory paths exist

### Debug Commands

```python
# Enable debug logging
import logging
logging.getLogger('app.utils.catchup_sync').setLevel(logging.DEBUG)

# Check specific server status
from app.models import SyncServer
server = SyncServer.query.filter_by(name='problematic-server').first()
print(f"Last sync: {server.last_sync}")
print(f"Last ping: {server.last_ping}")
print(f"Ping success: {server.ping_success}")

# Manual catch-up for specific server
from app.utils.catchup_sync import catchup_sync_manager
result = catchup_sync_manager.perform_catchup_sync(server)
print(result)
```

## Security Considerations

1. **API Authentication**: Catch-up endpoints use existing API key authentication
2. **Data Validation**: All synchronized data goes through existing validation
3. **Access Control**: Respects existing user permissions and team isolation
4. **Audit Trail**: All catch-up operations are logged for security review

## Integration

The catch-up system integrates seamlessly with existing components:

- **Real-time Sync**: Works alongside existing real-time synchronization
- **Change Tracking**: Uses existing database change tracking infrastructure  
- **Multi-server Sync**: Extends current multi-server sync capabilities
- **User Management**: Respects team isolation and user permissions
- **File Monitoring**: Leverages existing file integrity monitoring

## Performance Impact

- **Memory Usage**: Batch processing limits memory consumption
- **Database Load**: Efficient queries with timestamp indexing
- **Network Traffic**: Only changed data is synchronized
- **CPU Usage**: Background processing minimizes impact on main application

## Future Enhancements

Potential improvements for future versions:

1. **Compression**: Compress large change batches for faster transfer
2. **Delta Sync**: More efficient file synchronization using binary diffs
3. **Priority Queues**: Prioritize critical data types during catch-up
4. **Conflict Resolution**: Advanced conflict resolution for concurrent changes
5. **Metrics Dashboard**: Real-time catch-up monitoring and statistics

---

This offline server catch-up system ensures your multi-server scouting network maintains data consistency even when individual servers experience downtime, providing robust and reliable synchronization for critical scouting operations.
