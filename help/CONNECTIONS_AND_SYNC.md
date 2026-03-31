# Connections and Sync

This page explains what to expect from sync and what to do when it fails.

## Sync types

- **Real-time sync**: fast updates between connected devices
- **Catch-up sync**: recovers missed data after outages
- **Alliance sync**: shares alliance scouting data when enabled
- **API sync**: imports event/team/match data from external APIs

## What to check first

- Connection indicator is healthy
- Devices are using the same event and environment
- API credentials are valid (if using API sync)

## If devices disagree on data

1. Wait briefly for real-time/catch-up sync
2. Trigger manual sync from admin tools
3. Refresh both devices and re-check entries
4. If still mismatched, review sync logs/monitor

## Alliance sync notes

- Alliance sharing only works for active alliance members
- Shared match data can be visible across alliance teams
- Team-private data remains isolated unless explicitly shared

Inline help icons on alliance screens can be toggled in **Settings > Show inline help icons**.

## API sync notes

- Configure at least one provider (TBA and/or FIRST)
- Keep one provider as fallback for reliability
- Test with a known event code before competition use

## Best practice for events

- Keep one server instance as the primary source of truth
- Verify sync health before qualification matches begin
- Keep QR transfer available as an offline backup path

## Common Sync Problems

### High Queue Size
- Indicates sync worker overloaded or stuck
- Check server logs for errors
- Restart sync worker (Admin > Restart Services)
- Consider reducing sync frequency

### Sync Worker Not Running
- Worker may have crashed
- Check application logs
- Restart application
- Verify no database corruption

### Frequent Disconnections
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

- See the **Technical Details** section on this page for advanced synchronization details
- Check `DUAL_API_README.md` for API integration details
- Review `TROUBLESHOOTING.md` for common sync issues
- Contact your team's admin or technical lead
- Check GitHub issues for known bugs/workarounds 