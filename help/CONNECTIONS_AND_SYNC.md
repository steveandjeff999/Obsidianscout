# Connections and Real-Time Sync Guide

Obsidian-Scout features multiple synchronization systems to ensure data consistency across devices, servers, and alliance partners.

## Overview

Sync mechanisms available:
- **Real-Time Replication**: Instant websocket-based sync for live collaboration
- **Catch-Up Sync**: Periodic synchronization for devices that were offline
- **Alliance Sync**: Share data with alliance partners during competitions
- **API Sync**: Automated imports from FIRST API and The Blue Alliance
- **Server-to-Server Sync**: Multi-instance deployments stay synchronized

## Real-Time Replication

### How It Works

- Uses **WebSocket** technology (Socket.IO) for bidirectional communication
- Changes propagate instantly (<100ms typically)
- Supports multiple concurrent users
- Automatic reconnection if connection drops
- Queue-based reliability - no data loss during brief disconnections

### Supported Operations

- **Scouting data**: New entries, edits, deletions
- **Pit scouting**: Team information updates
- **Strategy drawings**: Real-time collaborative canvas
- **Chat messages**: Direct messages, group chat
- **Configuration changes**: Game config, pit config updates
- **Match data**: Score updates, scheduling changes

### Monitoring Real-Time Sync

1. Check **connection indicator** in navbar (green dot = connected)
2. Go to **Admin** > **Sync Monitor** for detailed status
3. View queue size and worker status
4. See last sync timestamp
5. Monitor error rates

### Performance Considerations

- Optimized for low-bandwidth scenarios (minimum 3G connection)
- Data compressed before transmission
- Batching reduces overhead for bulk operations
- Priority queue ensures critical updates go first

## Catch-Up Sync

### Purpose

Catch-up sync handles scenarios where devices were offline or real-time sync failed:
- Devices returning from network outage
- New devices joining existing deployment
- Recovering from sync failures
- Periodic validation of data consistency

### Automatic Catch-Up

- Runs every **5 minutes** by default (configurable)
- Compares local database timestamps with remote
- Identifies missing or outdated records
- Downloads and applies changes
- Minimal bandwidth usage (only transfers differences)

### Manual Catch-Up Trigger

1. Go to **Admin** > **Sync Monitor**
2. Click **Trigger Catch-Up Sync**
3. Select sync scope:
   - **Full**: All tables
   - **Teams**: Team data only
   - **Matches**: Match data only
   - **Scouting Data**: Match scouting entries
4. Monitor progress indicator
5. Status updates in real-time

### Catch-Up Scheduler

- Background process runs continuously
- Configurable intervals in `app_config.json`
- Logs all operations for troubleshooting
- Automatically retries failed operations
- Exponential backoff for persistent errors

## Alliance Sync

### What is Alliance Sync?

During FRC competitions, teams often form alliances and need to share scouting data. Alliance Sync enables secure, controlled data sharing between alliance partners.

### Setting Up an Alliance

1. **Admin user** goes to **Alliances** > **Scouting Alliances**
2. Click **Create Alliance**
3. Enter alliance name (e.g., "Playoff Alliance 1")
4. Invite partner teams by team number
5. Partners receive invitation and can accept/decline

### Alliance Member Management

- **Owners** can invite/remove members
- **Members** can view shared data
- Members can leave alliance anytime
- All actions logged for audit trail

### Data Sharing in Alliances

**What gets shared:**
- Match scouting data for common opponents
- Team rankings and analysis
- Strategy notes (if opted in)
- Match predictions

**What does NOT get shared:**
- Pit scouting data (unless explicitly shared)
- Internal team notes marked "private"
- User account information
- Configuration settings

### Inline help icons
The Scouting Alliances pages now include small help icons (a question-mark) next to major headings and controls. Hover (desktop) or tap (mobile) these icons to view short, contextual popovers explaining the feature. If you prefer not to see these inline hints, disable them in **Settings → Show inline help icons**.


### Alliance Sync Frequency

- Real-time sync for active matches
- Every **30 seconds** for upcoming matches
- Every **3 minutes** for historical data
- On-demand sync available

### Security & Privacy

- Alliance data isolated from other teams
- Token-based authentication for all sync operations
- Members can revoke sharing anytime
- No data shared without explicit alliance membership
- Audit logs track all data access

## API Sync (External Data Sources)

### Dual API Support

Obsidian-Scout integrates with official FRC data sources:

#### FIRST API (Official)
- Event schedules
- Match results and scores
- Team registrations
- Rankings and standings

#### The Blue Alliance API
- Fallback if FIRST API unavailable
- Historical data access
- Additional statistics
- OPR/DPR/CCWM calculations

### Configuring API Sync

1. Go to **Admin Settings** > **Configuration** > **API Settings**
2. **For FIRST API:**
   - Enter username
   - Enter authorization token
   - Set base URL (default: https://frc-api.firstinspires.org)
3. **For The Blue Alliance:**
   - Enter API key (get from thebluealliance.com/account)
   - Set base URL (default: https://www.thebluealliance.com/api/v3)
4. Choose **preferred API source** (FIRST or TBA)
5. Enable **auto-sync** toggle
6. Set sync interval (default: 3 minutes)
7. Save configuration

### Auto-Sync Behavior

- Syncs current event automatically
- Updates team list for event
- Imports match schedule
- Updates match scores as they're posted
- Fallback to secondary API if primary fails
- Logs all API requests for debugging

### Manual API Sync

1. Go to **Teams** or **Matches** page
2. Click **Sync from API** button
3. Select event (or use current event)
4. Wait for completion notification
5. Review imported data

## Server-to-Server Sync

### Multi-Instance Deployments

For large teams or multi-site operations, multiple Obsidian-Scout servers can sync:

### Adding a Remote Server

1. Go to **Admin** > **Server Management**
2. Click **Add Server**
3. Enter server details:
   - Name (e.g., "Pit Computer")
   - Host URL (e.g., "https://192.168.1.50:8080")
   - API key for authentication
4. Test connection
5. Enable sync

### Sync Modes

**Full Sync:**
- Entire database synchronized
- Used for initial setup or major sync issues
- Can take several minutes

**Incremental Sync:**
- Only changes since last sync
- Runs every 1-5 minutes
- Efficient for ongoing operations

**Real-Time Forwarding:**
- Changes pushed immediately to other servers
- Sub-second latency
- Requires persistent connection

### File Synchronization

Beyond database sync, files also sync:
- Configuration files (game_config.json, pit_config.json)
- Uploaded images (pit photos, team logos)
- Custom page definitions
- Strategy drawing backgrounds

**Blocked from sync (safety):**
- Database files (*.db, *.sqlite)
- Log files
- SSL certificates
- Application code

## Sync Monitoring

### Sync Monitor Dashboard

1. Navigate to **Admin** > **Sync Monitor**
2. View live statistics:
   - Active connections
   - Queue sizes
   - Sync worker status
   - Recent operations
   - Error rates
3. Real-time updates via WebSocket

### Key Metrics

- **Queue Size**: Number of pending operations (should be near 0)
- **Worker Running**: Status of background sync worker
- **Last Sync**: Timestamp of most recent sync
- **Error Count**: Failed operations (investigate if >0)
- **Connected Devices**: Number of active WebSocket connections

### Troubleshooting Sync Issues

#### High Queue Size
- Indicates sync worker overloaded or stuck
- Check server logs for errors
- Restart sync worker (Admin > Restart Services)
- Consider reducing sync frequency

#### Sync Worker Not Running
- Worker may have crashed
- Check application logs
- Restart application
- Verify no database corruption

#### Frequent Disconnections
- Check network stability
- Verify firewall not blocking WebSocket
- Inspect browser console for errors
- Try different network

## Best Practices

### For Event Day

1. **Test sync before event**:
   - Verify all devices connect
   - Simulate high load
   - Test offline/online transitions

2. **Monitor throughout day**:
   - Check sync dashboard hourly
   - Watch for error spikes
   - Ensure critical devices syncing

3. **Backup strategy**:
   - Manual QR code transfer if sync fails
   - USB transfer as last resort
   - Keep offline backups

### For Alliance Partners

1. **Establish alliance early** (before quarterfinals)
2. **Verify data sharing working** (test match or two)
3. **Coordinate on strategy** (who scouts what)
4. **Regular sync checks** (especially before critical matches)

### For Multi-Server Setup

1. **Designate primary server** (authoritative for configs)
2. **Test failover** (ensure secondary can take over)
3. **Monitor lag** (should be <5 seconds)
4. **Backup regularly** (automated if possible)

## Technical Details

### WebSocket Protocol

- Uses Socket.IO library
- Supports HTTP/HTTPS
- Automatic transport fallback (WebSocket > polling)
- Custom event namespaces for isolation

### Database Change Tracking

- Timestamp-based change detection
- Incremental sync uses `updated_at` column
- Change log table for audit trail
- Conflict resolution: last-write-wins (configurable)

### Security Considerations

- All sync traffic encrypted (HTTPS/WSS)
- API keys for server-to-server auth
- Session cookies for user requests
- Rate limiting prevents abuse
- IP whitelisting available for server sync

## Need Help?

- See `REALTIME_SYNC_README.md` for advanced real-time features
- Check `DUAL_API_README.md` for API integration details
- Review `TROUBLESHOOTING.md` for common sync issues
- Contact your team's admin or technical lead
- Check GitHub issues for known bugs/workarounds 