# Remote Server Update Instructions

## Issue: Remote Server Update HTTP 500 Error

When trying to update remote servers, you may get HTTP 500 errors with "Updater script not found on server". This happens when remote servers are running older versions that don't have the updated remote updater script.

## Solution Options

### Option 1: Manual Update (Immediate Fix)

1. **Download the latest release**:
   - Go to: https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip
   - Download and extract the ZIP file

2. **Copy the updater scripts to the remote server**:
   ```
   Copy these files to the remote server's root directory:
   - app/utils/remote_updater.py
   - simple_remote_updater.py
   - sync_config_manager.py
   ```

3. **Update the remote server**:
   - Stop the remote server
   - Copy the updated files over (preserving instance, uploads, config folders)
   - Restart the remote server

### Option 2: Use Simple Remote Updater

If you can access the remote server directly:

1. **Copy `simple_remote_updater.py` to the remote server**
2. **Run the simple updater**:
   ```bash
   python simple_remote_updater.py --zip-url https://github.com/steveandjeff999/Obsidianscout/archive/refs/heads/main.zip --port 8081 --use-waitress
   ```
   (Replace 8081 with your server's actual port)

### Option 3: Future-Proof Setup

Once you've updated the remote server once using Option 1 or 2:

1. **Verify the update worked**:
   - The remote server should now have `app/utils/remote_updater.py`
   - The sync API should now support remote updates

2. **Test remote updates**:
   - From your main server's sync dashboard
   - Click "Update Server" on the remote server
   - Should now work without HTTP 500 errors

## Configuration Fix Applied

The following issues were also fixed in the update system:

1. **Port Mismatch**: Updates now use the correct port for each server (was hardcoded to 8080)
2. **Windows Compatibility**: Remote updater now works on Windows systems
3. **Sync Server Preservation**: Sync server lists are automatically preserved during updates
4. **Better Error Messages**: More detailed error information for troubleshooting

## Verification

After updating, you can verify the fix worked by:

1. **Check sync server config**: `python sync_config_manager.py --verify`
2. **Test server connection**: `python test_server_connection.py`
3. **Try remote update**: From sync dashboard, click "Update Server"

## Status

-  **Root Cause Identified**: Remote servers missing updated updater scripts
-  **Windows Compatibility**: Fixed Unix-specific code in remote_updater.py
-  **Port Configuration**: Fixed hardcoded port issue 
-  **Sync Preservation**: Automatic sync server config backup/restore
-  **Fallback Options**: Multiple updater script locations checked
- ⏳ **Manual Update Required**: One-time manual update of remote servers needed

After the manual update, all future updates should work automatically through the sync dashboard.
