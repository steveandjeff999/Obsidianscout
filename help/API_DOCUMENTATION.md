# OBSIDIAN-Scout API Documentation

This document provides a concise reference for the OBSIDIAN-Scout HTTP API used by the app, integrations, and sync services. It is intended for developers building clients, scripts, or integrations.

Contents
- Overview
- Authentication
- Common request/response patterns
- Important endpoints (api/v1)
- Sync and realtime considerations
- Examples
- Related documentation

## Overview
The OBSIDIAN-Scout API is a RESTful HTTP API exposing endpoints for user management, scouting data (events, matches, teams), file synchronization, and administrative actions. The server returns JSON for most API endpoints. Some internal endpoints and sync channels use custom payloads — see Sync documentation.

Base URL
- For local or deployed installations, requests are made to the host where the application runs, e.g. `https://<your-host>/`.

Content type
- `application/json` for JSON requests/responses.

Errors
- Standard HTTP status codes are used. Error responses include an `error` or `errors` field with additional details where applicable.

## Authentication
The application uses session-based authentication (cookie + CSRF) for browser clients and token-based or API-key access for programmatic clients in some deployments. See `AUTH_README.md` in this help folder for setup and token lifecycle.

Highlights:
- Login endpoint sets an authenticated session cookie.
- API tokens may be issued for service accounts; tokens should be sent in the `Authorization: Bearer <token>` header.
- Protect CSRF for browser-based POST/PUT/PATCH/DELETE actions.

See `AUTH_README.md` for step-by-step examples.

## Common request/response patterns
- Pagination: endpoints returning lists commonly accept `page`, `per_page`, `limit`, or `offset` query parameters. Check the specific endpoint for supported params.
- Timestamps: ISO 8601 strings in UTC (e.g. `2025-09-21T14:23:00Z`).
- IDs: integer primary keys are commonly used for records like `team_id`, `match_id`, `event_id`.

## Important endpoints (api/v1)
The project exposes a versioned API under the `/api/v1` prefix. Below are the primary endpoints implemented in `app/routes/api_v1.py` (use these as the canonical reference):

- `GET /api/v1/info` — basic API info and the current API key status (returns a list of available endpoints and server time).

- Teams
  - `GET /api/v1/teams` — list teams filtered to the API key's registered scouting team. Supports `event_id`, `team_number`, `limit`, and `offset` query params.
  - `GET /api/v1/teams/<team_id>` — get detailed team info and recent matches (scoped to API key's scouting team).

- Events
  - `GET /api/v1/events` — list events (supports `code`, `location`, `limit`, `offset`).
  - `GET /api/v1/events/<event_id>` — get event details, teams and recent matches (scoped by API key).

- Matches
  - `GET /api/v1/matches` — list matches (supports `event_id`, `match_type`, `team_number`, `match_number`, `limit`, `offset`).
  - `GET /api/v1/matches/<match_id>` — get match details and any scouting entries for that match (scoped by API key).

- Scouting Data
  - `GET /api/v1/scouting-data` — list scouting entries (supports `team_id`, `match_id`, `scout`, `limit`, `offset`).
  - `POST /api/v1/scouting-data` — create a new scouting data entry (expects JSON with `team_id`, `match_id`, `data`, `scout`).

- Analytics
  - `GET /api/v1/analytics/team-performance` — basic analytics for a team (requires `team_id` or `team_number`, optional `event_id`).

- Sync and Admin
  - `GET /api/v1/sync/status` — returns counts and basic sync availability for a requesting team.
  - `POST /api/v1/sync/trigger` — trigger a sync operation (JSON `type` field: `full`, `teams`, `matches`, or `scouting_data`).
  - `GET /api/v1/team-lists/do-not-pick` — get do-not-pick entries for the requesting team.
  - `GET /api/v1/health` — simple health check endpoint.

Note: many endpoints enforce "scouting team" isolation: API keys are often tied to a scouting team number and results are filtered to that team's scope. See the `info` endpoint for the key details.

## Sync and realtime considerations
OBSIDIAN-Scout supports multiple sync mechanisms; some installations use SQLite-based catch-up syncing while others use realtime websocket channels. Refer to `REALTIME_SYNC_README.md` and `DUAL_API_README.md` for full details.

If you are integrating sync or real-time features, consult `app/routes/realtime_api.py`, `app/routes/litesync_api.py`, and `app/routes/sync_api.py` for implementation specifics and websocket channel names.

## Examples
cURL (login, then get teams):

```powershell
# login (example)
curl -i -X POST "https://<host>/login" -d '{"username":"admin","password":"secret"}' -H "Content-Type: application/json" -c cookies.txt

# use cookie to list teams
curl -i -X GET "https://<host>/api/v1/teams" -b cookies.txt
```

Bearer token example:

```powershell
curl -H "Authorization: Bearer <TOKEN>" "https://<host>/api/v1/teams"
```

File upload example (multipart):

```powershell
curl -X POST "https://<host>/api/files" -H "Authorization: Bearer <TOKEN>" -F "file=@scout.csv"
```

## Related documentation
- `AUTH_README.md` — authentication and tokens
- `REALTIME_SYNC_README.md` — realtime sync channels and websocket usage
- `DUAL_API_README.md` — additional notes on dual API setups and external data sources
- `SETUP_INSTRUCTIONS.md` — deployment and installation steps
- `app/routes/api_v1.py` — the canonical implementation of the v1 HTTP API (inspect for exact param names and behaviors)

## Where to find actual routes
If you need the exact route names, inspect the server `app/routes/` directory. Many endpoints are defined there and may include blueprint prefixes or route variable names.

## OBSIDIAN-Scout API Reference (detailed)

This document is a developer-oriented reference for the HTTP APIs implemented in the OBSIDIAN-Scout application. It focuses on the most widely-used endpoints (versioned API under `/api/v1`), server-to-server sync APIs (`/api/sync`), and real-time replication endpoints (`/api/realtime`). Use the mention of a source file (e.g. `app/routes/api_v1.py`) as the canonical implementation.

Table of contents
- Overview
- Authentication & API keys
- Common patterns (pagination, timestamps, errors)
- Detailed `/api/v1` endpoints with parameters and example payloads
- Server-to-server sync (`/api/sync`) overview and critical endpoints
- Real-time replication (`/api/realtime`) endpoints
- API key management (`/api/keys`)
- Examples and best practices
- OpenAPI / machine-readable spec (next steps)
- Related docs and where to look in code

## Overview
Base URL: `https://<your-host>/` (or `http://localhost:<port>/` in development). The main application exposes:
- A versioned JSON API at `/api/v1` (primary client integration surface).
- Sync and replication endpoints under `/api/sync` and `/api/realtime` used for server-to-server and realtime operations.

Responses: JSON by default. Content type should be `application/json` for JSON requests.

Security note: Many endpoints filter results by the API key's associated `scouting_team_number` or require authenticated users with appropriate roles. Administrative and API-key management endpoints require `admin` or `superadmin` roles.

## Authentication & API keys
- Browser sessions: use the login form at `/auth/login` — this issues a session cookie and requires CSRF protection for modifying requests.
- API keys: manage them under the `api_keys` blueprint (`/api/keys`). Programmatic requests should send API keys as `Authorization: Bearer <token>` (the API validation utilities read and verify the key and apply rate limits and scoping).
- Typical flow for programmatic access:
  1. Admin creates an API key (via the web UI or `POST /api/keys` when authenticated as an admin).
  2. The key is tied to a `scouting_team_number` and a `permissions` object (see `app/routes/api_keys.py`).
  3. The client includes the API key in `Authorization` header for requests to `/api/v1`.

Rate limiting: API keys include a `rate_limit_per_hour` setting. Requests exceeding this will be blocked/returned with appropriate errors (see API key usage endpoints).

## Common patterns
- Pagination: `limit`, `offset` (also `page` / `per_page` in some endpoints). Default limits may be applied; `limit` is often capped (e.g., 1000).
- Timestamps: ISO 8601 (UTC) — e.g. `2025-09-21T14:23:00Z`.
- Error responses: typically `{ "error": "message" }` or `{ "errors": [...] }` with appropriate HTTP status codes (400, 401, 403, 404, 500).

## Detailed /api/v1 endpoints
All these endpoints are implemented in `app/routes/api_v1.py`. Authentication decorators (e.g. `team_data_access_required`, `scouting_data_read_required`, `scouting_data_write_required`, `sync_operations_required`, `analytics_access_required`) enforce access control.

### 1) GET /api/v1/info
- Description: Returns API version info, server time, current API key details and a small endpoint map.
- Auth: `team_data_access_required` (API key required)
- Example response (partial):
  {
    "success": true,
    "api_version": "1.0",
    "api_key": { "id": 12, "name": "Team42Key", "team_number": 42, "permissions": {...} },
    "server_time": "2025-09-21T...Z",
    "endpoints": { "teams": "/api/v1/teams", ... }
  }

### 2) Teams
- GET /api/v1/teams
  - Description: List teams scoped to API key's `scouting_team_number`.
  - Query params: `event_id` (int), `team_number` (int), `limit` (int, default 100), `offset` (int)
  - Auth: `team_data_access_required`
  - Response fields: `teams` (array of team objects), `count`, `total_count`, `limit`, `offset`, `requesting_team`

- GET /api/v1/teams/<team_id>
  - Description: Get detailed team info and recent matches. Scoped to the API key's team if applicable.
  - Auth: `team_data_access_required`
  - Response includes `id`, `team_number`, `team_name`, `location`, `scouting_team_number`, `events`, `scouting_data_count`, `recent_matches`

Team object schema (example):
  {
    "id": 123,
    "team_number": 254,
    "team_name": "The Cheesy Poofs",
    "location": "San Jose, CA",
    "scouting_team_number": 42,
    "events": [{"id": 5, "name": "CALA", "code": "CALA"}]
  }

### 3) Events
- GET /api/v1/events
  - Query params: `code`, `location`, `limit`, `offset`.
  - Auth: `team_data_access_required`
  - Response: list of events; each event includes `id`, `name`, `code`, `location`, `start_date`, `end_date`, `team_count`.

- GET /api/v1/events/<event_id>
  - Returns event details, teams and recent matches (scoped by API key's team membership for the event).

### 4) Matches
- GET /api/v1/matches
  - Query params: `event_id`, `match_type`, `team_number`, `match_number`, `limit`, `offset`.
  - Auth: `scouting_data_read_required`
  - Each match includes `id`, `match_number`, `match_type`, `event_id`, `red_alliance`, `blue_alliance`, `red_score`, `blue_score`, `winner`, `scouting_team_number`.

- GET /api/v1/matches/<match_id>
  - Returns match details and associated scouting entries (scoped by API key).

Match example:
  {
    "id": 456,
    "match_number": 12,
    "match_type": "Qualification",
    "event_id": 5,
    "red_alliance": "254,1114,469",
    "blue_alliance": "148,2056,971",
    "red_score": 150,
    "blue_score": 120,
    "winner": "red",
    "scouting_team_number": 42
  }

### 5) Scouting Data
- GET /api/v1/scouting-data
  - Query params: `team_id`, `match_id`, `scout` (search), `limit`, `offset`.
  - Auth: `scouting_data_read_required`
  - Response contains an array of scouting entries with fields: `id`, `team_id`, `match_id`, `data` (JSON), `scout`, `timestamp`, `scouting_team_number`.

- POST /api/v1/scouting-data
  - Description: Create a new scouting data entry.
  - Auth: `scouting_data_write_required` (API key permission required)
  - Required JSON body:
    {
      "team_id": 123,
      "match_id": 456,
      "data": { ... game-specific JSON ... },
      "scout": "alice"
    }
  - Success response: 201 with created entry metadata (id, team_id, match_id, scout, timestamp).

Scouting data schema notes: The model stores `data_json` (game-specific arbitrary JSON). The code provides helper methods to convert and migrate keys to perm_ids. When possible, follow the current game config format (see game config utilities in `app/utils/config_manager.py`).

### 6) Analytics
- GET /api/v1/analytics/team-performance
  - Params: `team_id` (int) or `team_number` (int) required, optional `event_id`.
  - Auth: `analytics_access_required`
  - Returns aggregate stats such as `total_scouting_entries`, `unique_matches_scouted`, `data_quality_score`, `last_scouted`.

### 7) Sync / Admin
- GET /api/v1/sync/status
  - Auth: `sync_operations_required`
  - Returns counts for teams, matches, scouting_data, events and a `sync_available` flag.

- POST /api/v1/sync/trigger
  - Auth: `sync_operations_required`
  - JSON body: `{ "type": "full" | "teams" | "matches" | "scouting_data" }` (default `full`).
  - Returns `sync_id` and an estimated completion time.

- GET /api/v1/team-lists/do-not-pick
  - Returns entries for the requesting API key's team (do-not-pick list), including `team_id`, `team_number`, `team_name`, `reason`, `timestamp`.

- GET /api/v1/health
  - Simple health/status endpoint.

## Server-to-server sync (`/api/sync`)
These endpoints are implemented in `app/routes/sync_api.py` and are used for server-to-server operations, catch-up sync, file transfers, and advanced SQLite-based reliable sync.

Highlights (not exhaustive):
- GET /api/sync/ping — health check for sync subsystem.
- GET /api/sync/changes?since=<iso8601>&catchup_mode=true — returns DatabaseChange entries since the provided timestamp.
- POST /api/sync/receive-changes — accept a list of changes (JSON) from another server and apply them.
- POST /api/sync/servers — add a remote sync server (name/host required).
- POST /api/sync/files/upload — multipart file upload for instance, config, or uploads (database files are explicitly blocked for safety).
- GET /api/sync/files/checksums?path=instance — list checksums for files in a directory (useful for catch-up and partial sync).

Advanced features (SQLite3 automatic sync): endpoints like `/api/sync/sqlite3/...` support automatic zero-data-loss full sync, optimized change capture, and reliability reports. These endpoints include checksum verification and batch handling for large transfers.

Security & safety notes for `/api/sync`:
- File upload/download explicitly blocks syncing database files to avoid corruption.
- Many endpoints require mutual server trust: these are intended for server-to-server use within trusted networks.

## Real-time replication (`/api/realtime`)
Implemented in `app/routes/realtime_api.py`.

- POST /api/realtime/receive — apply a single real-time operation from another server. Payload example:
  {
    "operation": { "type": "insert", "table": "scouting_data", "data": {...}, "record_id": 123 },
    "source_server_id": "server_A"
  }

- GET /api/realtime/ping — simple health check for real-time replication.

The real-time receiver maps table names to models and applies `insert`, `update`, or `delete` operations while disabling replication loops using `DisableReplication()`.

## API key management (`/api/keys`)
Implemented in `app/routes/api_keys.py`.

- GET /api/keys/ — list API keys for the current user's team (requires login + admin role).
- POST /api/keys/ — create a new API key. Required JSON: `{ "name": "Key name", "rate_limit_per_hour": 1000, "description": "optional" }`.
- GET /api/keys/<id> — get key details and usage stats.
- PUT /api/keys/<id> — update key metadata and rate limits (superadmin required to change permissions field).
- DELETE /api/keys/<id> — deactivate the key (soft delete).
- GET /api/keys/<id>/usage?days=30 — returns per-day usage stats and detailed entries.

API key permissions object (default sample):
  {
    "team_data_access": true,
    "scouting_data_read": true,
    "scouting_data_write": false,
    "sync_operations": true,
    "analytics_access": true
  }

Note: API key management endpoints require an authenticated admin user (web UI or calls authenticated by session cookie). Keys are created for a team's scope and will be filtered by `scouting_team_number`.

## Examples & recipes
1) Login with curl (web session)

```powershell
# Form POST -> gets cookies stored in cookies.txt
curl -i -X POST "https://<host>/auth/login" -F "username=admin" -F "password=secret" -F "team_number=42" -c cookies.txt

# Use cookie for subsequent requests
curl -i -X GET "https://<host>/api/v1/teams" -b cookies.txt
```

2) Using an API key (bearer token)

```powershell
curl -H "Authorization: Bearer eyJhbGci..." "https://<host>/api/v1/teams?limit=50"
```

3) Create scouting data (JSON)

```powershell
curl -X POST "https://<host>/api/v1/scouting-data" \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"team_id": 123, "match_id": 456, "data": {"auto":true,"cells":5}, "scout":"alice"}'
```

4) Server-to-server change polling (catch-up)

```powershell
curl "https://<host>/api/sync/changes?since=2025-09-20T00:00:00Z&catchup_mode=true&server_id=remote1"
```

## Error handling and edge cases
- 400 Bad Request: missing required params or invalid payloads.
- 401 Unauthorized / 403 Forbidden: not authenticated or insufficient permissions (role or API key scope).
- 404 Not Found: resource not found or not accessible to your API key's scouting team.
- 429 Too Many Requests: rate limit exceeded for API key (enforced per `rate_limit_per_hour`).
- 500 Internal Server Error: server-side errors — check server logs for traceback.

Edge cases to consider while integrating:
- Team isolation: API keys are scoped to a `scouting_team_number`. Requests for teams/events outside that scope will be denied (403/404).
- Large datasets: use `limit`/`offset` and avoid very large `limit` values; use catch-up endpoints for sync bulk operations.
- File sync: never attempt to upload or download database files via `/api/sync/files` — the server blocks database filenames and extensions explicitly.


## Where to look in code (quick links)
- `app/routes/api_v1.py` — canonical v1 API endpoints and request/response behaviors.
- `app/routes/sync_api.py` — server-to-server sync, file sync, SQLite3-specific sync endpoints.
- `app/routes/realtime_api.py` — real-time replication endpoints used by other servers.
- `app/routes/api_keys.py` — API key management and usage stats.
- `app/models.py` — database models used by the endpoints (Team, Match, ScoutingData, User, Event).

## Related docs
- `help/AUTH_README.md` — details about authentication and token lifecycle.
- `help/REALTIME_SYNC_README.md` — websocket-based realtime sync and alliance selection notes.
- `help/DUAL_API_README.md` — info about external APIs (FIRST API & The Blue Alliance) used for event/team data.
- `help/SETUP_INSTRUCTIONS.md` — deployment and instance setup notes.


