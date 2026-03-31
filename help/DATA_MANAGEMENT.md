# Data Management Guide

Use this page for day-to-day importing, exporting, and data verification.

## Importing Data
1. Go to the **Data** page.
2. Choose **Import Excel** or **Import QR**.
3. Upload your file or pasted payload.
4. Review the import summary for added/updated/skipped records.
5. Verify imported records in scouting lists, team views, or graphs.

## Exporting Data
1. Go to the **Data** page.
2. Choose the export action (for example, Excel export).
3. Save the file and confirm the row counts look correct.
4. Keep exports with your event backups for recovery.

## Basic Validation Checklist

- Confirm current event is correct before imports.
- Spot-check a few teams and matches after import.
- If results look incomplete, verify permissions and filters.
- Use QR transfer as a fallback when network sync is unreliable.

## API Sync
- For automatic team/match syncing and API fallback behavior, see `DUAL_API_README.md`.
- For network and realtime sync diagnosis, see `CONNECTIONS_AND_SYNC.md`.