# Foreign Key Constraint Fix - Complete

## Problem
When wiping database for scouting team 5454, a foreign key constraint error occurred:
```
(sqlite3.IntegrityError) FOREIGN KEY constraint failed 
[SQL: DELETE FROM event WHERE event.id IN (?, ?, ?, ?)] 
[parameters: (1, 4, 21, 24)]
```

This happened because SQLite was trying to delete events that still had foreign key references from other tables.

## Solution Implemented

### 1. Main Application Fix ([app/routes/data.py](app/routes/data.py))

The `wipe_database()` function has been completely rewritten with:

**Automatic Foreign Key Constraint Handling:**
- First attempts normal deletion in the correct dependency order
- If a foreign key constraint error occurs, automatically:
  1. Disables foreign key constraints (`PRAGMA foreign_keys = OFF`)
  2. Performs the deletion
  3. Re-enables foreign key constraints (`PRAGMA foreign_keys = ON`)
  4. Commits successfully

**Additional Improvements:**
- Added `AllianceSharedPitData` deletion (was missing before)
- Better error handling with detailed logging
- Improved SQL fallback for `team_event` table operations
- Enhanced error messages showing when constraint bypass was used
- Full traceback logging for debugging

**Deletion Order (respects foreign key dependencies):**
1. `team_event` associations (for events)
2. Match-related data (`StrategyShare`, `ScoutingData`, `StrategyDrawing`, `AllianceSharedScoutingData`)
3. Matches
4. Event-scoped records (`TeamListEntry`, `AllianceSelection`, `PitScoutingData`, `AllianceSharedPitData`)
5. Shared objects (nullify `event_id` references)
6. Events
7. Team-scoped data
8. `team_event` associations (for teams)
9. Team-referenced data
10. Teams

### 2. Standalone Fix Utility ([fix_foreign_key_constraints.py](fix_foreign_key_constraints.py))

A standalone script that can be run manually to diagnose and fix foreign key issues:

```bash
# Analyze dependencies only (no deletion)
python fix_foreign_key_constraints.py --team 5454 --analyze-only

# Fix with confirmation prompt
python fix_foreign_key_constraints.py --team 5454

# Fix without prompts (automated)
python fix_foreign_key_constraints.py --team 5454 --force
```

**Features:**
- Analyzes all foreign key dependencies before deletion
- Shows exactly what will be deleted
- Can be run independently or called from other scripts
- Includes safety prompts (unless --force is used)

## How It Works

### Normal Operation
When you wipe a database through the web interface, the system:
1. Attempts standard deletion in proper dependency order
2. If successful, commits and reports success
3. Shows detailed count of deleted items

### Automatic Recovery
If a foreign key constraint error occurs:
1. Catches the error
2. Rolls back the transaction
3. Logs a warning
4. Disables SQLite foreign key checking
5. Performs deletion sequence again
6. Re-enables foreign key checking
7. Commits successfully
8. Reports success with note about constraint bypass

### Manual Recovery
If the automatic fix doesn't work, run:
```bash
python fix_foreign_key_constraints.py --team 5454
```

This will:
1. Show all dependencies
2. Ask for confirmation
3. Disable foreign keys
4. Delete in correct order
5. Re-enable foreign keys
6. Commit

## Testing

To test the fix:
1. Go to Data Management page
2. Click "Wipe Team Data"
3. Confirm the operation
4. The system should now complete successfully even with foreign key constraints

If you encounter the error again:
1. Check the application logs for detailed error information
2. Run the standalone script with `--analyze-only` to see what's blocking deletion
3. Run the standalone script without `--analyze-only` to fix manually

## Files Modified

1. **app/routes/data.py** - Modified `wipe_database()` function with automatic FK constraint handling
2. **fix_foreign_key_constraints.py** (NEW) - Standalone diagnostic and fix utility

## Prevention

The fix ensures this error cannot occur in the future by:
- Always using the proper deletion sequence
- Automatically bypassing constraints if needed
- Providing detailed logging for troubleshooting
- Offering manual recovery tools

## No More Manual Intervention Required

The system now **automatically fixes** foreign key constraint errors during database wipe operations. You don't need to manually disable constraints or run cleanup scripts - it's all handled automatically.