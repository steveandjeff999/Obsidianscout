# Mobile API: Syncing Teams & Matches 📡

## Overview
This document describes the mobile API endpoints related to synchronization of teams and matches from external sources (The Blue Alliance / FIRST API).

- GET `/api/mobile/sync/status` — Check last update timestamps (existing)
- POST `/api/mobile/sync/trigger` — **Trigger a server-side teams+matches sync** (new)

---

## GET /api/mobile/sync/status ✅
Returns the last update identifiers/timestamps for teams and matches for the mobile token's resolved scouting team.

Response example:

{
  "success": true,
  "server_time": "2025-12-31T12:00:00Z",
  "last_updates": {
    "teams": 12345,
    "matches": 12346
  }
}

Clients should poll this to know whether new data is available.

---

## POST /api/mobile/sync/trigger 🔄 (NEW)
Trigger a combined teams + matches sync for the server using the configured API source (TBA or FIRST, as configured on the server). This mirrors the admin/web endpoint `/api/sync-event`.

Security
- Requires a valid mobile JWT in `Authorization: Bearer <token>`.
- The mobile user must have the `admin` **or** `analytics` role. Requests by other users will return **403 Insufficient permissions**.

Behavior
- If alliance mode is active for the server/team, an alliance sync will be attempted first (safe no-op if not configured).
- The endpoint calls the same server-side sync functions used by the web admin UI, so behavior and results match the web-triggered sync.

Request
- Method: POST
- URL: `/api/mobile/sync/trigger`
- Headers: `Authorization: Bearer <token>`
- Body: none

Success response example:

{
  "success": true,
  "results": {
    "teams_sync": {"success": true, "message": "Teams sync attempted.", "flashes": []},
    "matches_sync": {"success": true, "message": "Matches sync attempted.", "flashes": []},
    "alliance_sync": {"triggered": false}
  }
}

Error responses:
- 401 Unauthorized — invalid/expired token
- 403 Forbidden — token user lacks required role
- 500 Internal Server Error — sync failed; check server logs

Notes
- Only use this from trusted mobile apps (admin/analytics users). The endpoint performs server-side changes and can be expensive for large events.
- Mobile clients that are not allowed to trigger syncs should instead poll `/api/mobile/sync/status`.

