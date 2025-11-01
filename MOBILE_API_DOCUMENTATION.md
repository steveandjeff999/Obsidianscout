# Mobile API Documentation

## Overview

The OBSIDIAN Scout Mobile API provides a comprehensive REST API for building mobile applications (iOS, Android, etc.) that can interact with the scouting platform. The API supports authentication, data retrieval, scouting data submission, and offline sync capabilities.

**Base URL:** `https://your-server.com/api/mobile`

**API Version:** 1.0

## Features

-  **JWT-based Authentication** - Secure token-based authentication with 7-day expiration
-  **Mobile-Optimized** - Designed specifically for mobile app constraints
-  **Offline Sync** - Bulk submission support for offline-first mobile apps
-  **Team Isolation** - Data automatically scoped to user's scouting team
-  **Real-time Data** - Access to live match and team data
-  **Comprehensive Coverage** - All scouting features available via API

---

## Authentication

### Login

Authenticate a user and receive a JWT token.

**Endpoint:** `POST /api/mobile/auth/login`

**Request Body:**
```json
{
  "username": "scout123",
  "password": "password123",
  "team_number": 5454
}
```

**Success Response (200):**
```json
{
  "success": true,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 42,
    "username": "scout123",
    "team_number": 5454,
    "roles": ["scout"],
    "profile_picture": "img/avatars/default.png"
  },
  "expires_at": "2024-01-08T12:00:00Z"
}
```

**Error Responses:**
- `400` - Missing credentials
- `401` - Invalid credentials
- `401` - Account inactive

**Error Codes:**
- `MISSING_CREDENTIALS`
- `INVALID_CREDENTIALS`
- `ACCOUNT_INACTIVE`

### Refresh Token

Refresh an authentication token before it expires.


List and fetch messages
-----------------------

The mobile API provides a single file-backed fetch endpoint to read messages for direct conversations and alliance chats:

- `GET /api/mobile/chat/messages?type=dm&user=<other_user_id>&limit=<n>&offset=<n>` — returns direct messages involving the authenticated user. When `user` is provided the endpoint returns the conversation between the authenticated user and that other user (other user must be on the same scouting team). When `user` is omitted the endpoint aggregates all direct-message files involving the authenticated user and returns a merged, sorted list.

- `GET /api/mobile/chat/messages?type=alliance&limit=<n>&offset=<n>` — returns alliance messages read from per-team group files named `alliance_<alliance_id>_group_chat_history.json` (the endpoint also falls back to any DB-held alliance chat rows if present). The authenticated user's active alliance is used to determine which per-team files are read.

Both endpoints return paginated results with `limit` (default 50) and `offset` (default 0). Messages are returned newest-first (sorted by timestamp).

Success response (200):
```json
{
  "success": true,
  "count": 10,
  "total": 123,
  "messages": [
    { "id": "uuid-1", "sender": "scout123", "recipient": "other", "text": "On my way", "timestamp": "2025-10-29T14:30:00Z" }
  ]
}
```

Notes:
- Messages are stored under `instance/chat` on the server. Direct messages are saved to `instance/chat/users/<team_number>/<user1>_<user2>_chat_history.json` where the users in the filename are sorted alphabetically for a consistent file path.
- Alliance messages are saved to per-team group files under `instance/chat/groups/<team_number>/alliance_<alliance_id>_group_chat_history.json`.
- The mobile API enforces team/alliance membership server-side. Clients must pass a valid JWT in `Authorization: Bearer <token>`.
```

---

---

## Chat API

Enable in-team and in-alliance messaging for scouts. The Chat API allows mobile clients to list chat-eligible members, create and list conversations, send messages, and fetch message history. All endpoints require a valid mobile JWT token in the `Authorization: Bearer <token>` header.

Permissions and scope
 - Users may message other users who are members of the same scouting team (scoping enforced by the token's `scouting_team_number`) or members of the user's current scouting alliance for the active event. The server MUST verify membership before delivering or persisting messages.
 - Team-isolation rules apply: users cannot message arbitrary users outside their team or alliance.

Base path
 - All Chat endpoints are under `/api/mobile/chat`

List chat-eligible members
-------------------------

Get a list of users you can message (team members and current alliance members).

Endpoint: `GET /api/mobile/chat/members`

Headers:
```
Authorization: Bearer <token>
```

Query Parameters:
- `scope` (optional) - `team` (default) or `alliance` — which membership list to return

Success Response (200):
```json
{
  "success": true,
  "members": [
    { "id": 42, "username": "scout123", "display_name": "Alex", "team_number": 5454 },
    { "id": 43, "username": "lead_scout", "display_name": "Morgan", "team_number": 5454 }
  ]
}
```

Errors:
- `401` - `AUTH_REQUIRED` or `INVALID_TOKEN`

Create / send a message
------------------------

Send a direct message to a user, or send to a conversation (group/alliance). Server enforces that recipients are in-scope.

Endpoint: `POST /api/mobile/chat/send`

Headers:
```
Authorization: Bearer <token>
Content-Type: application/json
```

Request Body (direct message example):
```json
{
  "recipient_id": 43,
  "body": "Good match — meet at the pit after the next round",
  "offline_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

Request Body (create in-alliance conversation example):
```json
{
  "conversation_type": "alliance",
  "body": "Alliance strategy: pick defensive positioning",
  "offline_id": "uuid-2"
}
```

Success Response (201):
```json
{
  "success": true,
  "message": {
    "id": 987,
    "conversation_id": 55,
    "sender_id": 42,
    "recipient_id": 43,
    "body": "Good match — meet at the pit after the next round",
    "created_at": "2025-10-29T14:35:12Z",
    "offline_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

Error codes:
- `400` - `MISSING_DATA`, `MESSAGE_TOO_LONG` (recommend limit: 4000 chars)
- `401` - `AUTH_REQUIRED` or `INVALID_TOKEN`
- `403` - `USER_NOT_IN_SCOPE` (attempt to message someone outside team/alliance)

List conversations
------------------

List conversations relevant to the authenticated user (direct and group/alliance).

Endpoint: `GET /api/mobile/chat/conversations`

Headers:
```
Authorization: Bearer <token>
```

Query Params:
- `limit` (optional, default: 50)
- `offset` (optional, default: 0)

Success Response (200):
```json
{
  "success": true,
  "conversations": [
    {
      "id": 55,
      "type": "direct",
      "title": "Alex",
      "last_message": "See you at the pit",
      "last_message_at": "2025-10-29T14:35:12Z",
      "unread_count": 2
    }
  ]
}
```

Fetch messages for a conversation
---------------------------------

Retrieve messages for a conversation (direct or alliance). The server enforces access control: only conversation members may fetch messages.

Endpoint: `GET /api/mobile/chat/conversations/{conversation_id}/messages`

Headers:
```
Authorization: Bearer <token>
```

Query Params:
- `limit` (optional, default: 50)
- `before` (optional ISO 8601 timestamp) — for pagination

Success Response (200):
```json
{
  "success": true,
  "messages": [
    { "id": 986, "sender_id": 43, "body": "On my way", "created_at": "2025-10-29T14:30:00Z" },
    { "id": 987, "sender_id": 42, "body": "Good match — meet at the pit", "created_at": "2025-10-29T14:35:12Z" }
  ],
  "count": 2
}
```

Mark messages read
------------------

Endpoint: `POST /api/mobile/chat/conversations/{conversation_id}/read`

Body:
```json
{ "last_read_message_id": 987 }
```

Response:
```json
{ "success": true }
```

Edit / Delete / React to messages (mobile)
-----------------------------------------

Mobile clients may edit, delete, or react to messages they have sent. These endpoints mirror the web UI behavior and emit the same Socket.IO events so clients (web and mobile) can update the UI in real time.

Common headers for these endpoints:
```
Authorization: Bearer <token>
Content-Type: application/json
```

1) Edit a message

Endpoint: `POST /api/mobile/chat/edit-message`

Request body:
```json
{
  "message_id": "uuid-1234",
  "text": "Updated message text"
}
```

Success response (200):
```json
{ "success": true, "message": "Message edited." }
```

Errors:
- `400` - missing fields (message_id and text required)
- `403` - not allowed (only the original sender may edit their messages; assistant messages cannot be edited)
- `404` - message not found

Notes:
- The server will set an `edited` flag and `edited_timestamp` on the persisted message.
- The server emits a `message_updated` Socket.IO event to the message participants (for DMs: sender and recipient) with payload: `{ message_id, text, reactions? }` so clients can update the message text in-place.

2) Delete a message

Endpoint: `POST /api/mobile/chat/delete-message`

Request body:
```json
{
  "message_id": "uuid-1234"
}
```

Success response (200):
```json
{ "success": true, "message": "Message deleted." }
```

Errors:
- `400` - missing message_id
- `403` - not allowed (only the original sender may delete their messages; assistant messages cannot be deleted)
- `404` - message not found

Notes:
- The server removes the message from the file-backed history and emits a `message_deleted` Socket.IO event to the message participants with payload `{ message_id }`.

3) React (toggle) to a message

Endpoint: `POST /api/mobile/chat/react-message`

Request body:
```json
{
  "message_id": "uuid-1234",
  "emoji": "👍"
}
```

Success response (200):
```json
{ "success": true, "reactions": [ { "emoji": "👍", "count": 2 }, { "emoji": "❤️", "count": 1 } ] }
```

Errors:
- `400` - missing message_id or emoji
- `404` - message not found

Notes:
- Reactions are toggled per-user: posting the same emoji again removes the user's reaction.
- The server stores individual reaction entries under `reactions` (per-user records) and also computes and persists a `reactions_summary` grouped list like `{ emoji, count }` for efficient client rendering.
- The server emits a `message_updated` Socket.IO event to the message participants (for DMs: sender and recipient) with payload `{ message_id, reactions }` where `reactions` is the grouped summary. Clients should treat `message_updated` payloads as possibly reaction-only updates (i.e., `text` may be omitted).

Client behavior tips
--------------------
- When handling `message_updated` socket events, mobile apps should check whether `data.text` is present before replacing the message body — reaction-only updates may omit the `text` field.
- Ensure your client sends a non-empty `emoji` string. The server will reject empty or missing emoji with a 400 error.
- The server enforces team/alliance scope and message ownership; expect `403` when attempting to edit/delete others' messages.


Group management (mobile)
-------------------------

Mobile clients can create and manage named group conversations (team-scoped). These endpoints are JWT-protected and operate on the same file-backed group storage used by the web UI and Socket.IO handlers (under `instance/chat/groups/<team_number>/`). Group names are sanitized (for example `/` is replaced with `_`) when stored.

Common headers:
```
Authorization: Bearer <token>
Content-Type: application/json
```

1) List groups

Endpoint: `GET /api/mobile/chat/groups`

Query params: none

Success response (200):
```json
{
  "success": true,
  "groups": [
    { "name": "pit_team", "member_count": 3, "is_member": true },
    { "name": "strategy", "member_count": 5, "is_member": false }
  ]
}
```

Notes:
- `is_member` indicates whether the authenticated mobile user is currently a member of the group.

2) Create a group

Endpoint: `POST /api/mobile/chat/groups`

Request body:
```json
{
  "group": "scouting_team_chat",
  "members": [ "alice", "bob", "carol" ]
}
```

Members should be provided as an array of usernames (team-scoped). The server will persist the group's member list and ensure a group chat history file exists.

Success response (201):
```json
{
  "success": true,
  "group": { "name": "scouting_team_chat", "members": ["alice","bob","carol"] }
}
```

Errors:
- `400` - `MISSING_DATA` (missing `group` or `members`)
- `401` - `AUTH_REQUIRED` / `INVALID_TOKEN`
- `403` - `USER_NOT_IN_SCOPE` (attempt to add users not on the team)

3) Manage group members

Endpoint: `GET /api/mobile/chat/groups/{group}/members`
Purpose: return the list of members for the named group.

Success response (200):
```json
{ "success": true, "members": ["alice","bob","carol"] }
```

Add members:

Endpoint: `POST /api/mobile/chat/groups/{group}/members`

Request body:
```json
{ "members": ["dave","erin"] }
```

Success response (200):
```json
{ "success": true, "members": ["alice","bob","carol","dave","erin"] }
```

Remove members:

Endpoint: `DELETE /api/mobile/chat/groups/{group}/members`

Request body:
```json
{ "members": ["erin"] }
```

Success response (200):
```json
{ "success": true, "members": ["alice","bob","carol","dave"] }
```

Notes / behavior details:

- Request body is optional. If you provide a JSON body with a `members` array the server will attempt to remove those usernames from the group. Example:

```json
{ "members": ["erin"] }
```

- If the request body is omitted or `members` is empty (for example, sending `{}` or an empty body), the API will default to removing the requesting user from the group. This makes it easy for clients to implement a "Leave group" action without needing to know the caller's username.

- Member removal is performed case-insensitively (the server compares trimmed, lowercased usernames) so casing mismatches in client-provided names won't prevent removal.

- The server persists the updated members list. If the group's members file did not previously exist, the handler treats that as an empty list, applies the removal, and writes the resulting list (it may write an empty list). The handler does not reliably return 404 for a missing members file — instead it persists the new state.

Example: curl to remove yourself (empty body / no members array)

```bash
curl -X DELETE "https://your-server.com/api/mobile/chat/groups/pit_team/members" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Return codes and errors:

- `200` — success; body contains the updated members list.
- `401` — `AUTH_REQUIRED` / `INVALID_TOKEN` when the JWT is missing or invalid.
- `403` — `USER_NOT_IN_SCOPE` when the requested removal would affect users not in the token's team or otherwise out of scope.
- `500` — `GROUP_SAVE_ERROR` if the server fails to persist the updated members list.

Note: unlike earlier doc wording, `400 MISSING_DATA` is not guaranteed for deletes — an empty or missing members array is intentionally interpreted as "remove the caller".

Notes and tips:
- Group messages may be sent using the existing `POST /api/mobile/chat/send` endpoint by including a `group` field in the payload, for example: `{ "group": "scouting_team_chat", "body": "Let's meet at the pit" }`.
- Group names are team-scoped; the same group name can exist on different teams without conflict because files are stored under the team's `instance/chat/groups/<team_number>/` directory.
- Current behavior: any authenticated team member may create groups and add/remove members. If you require stricter permissions (admins or leads only), implement role checks on the server side before calling these endpoints.

Real-time delivery (optional)
----------------------------

For near real-time messaging, the server may expose a WebSocket or server-sent events endpoint (implementation dependent). Suggested WebSocket path: `/api/mobile/chat/ws` with the JWT passed in the `Sec-WebSocket-Protocol` or as a query param. If implemented, messages delivered over the socket should follow the same permission checks.

Data model notes (server-side)
------------------------------
- Message: { id, conversation_id, sender_id, recipient_id (nullable for group), body (text), created_at (UTC), read (boolean), offline_id (optional) }
- Conversation: { id, type: direct|alliance|team, participant_ids, last_message_at }
- Index and partition messages by `scouting_team_number` to keep team isolation efficient.

Rate limits and limits
----------------------
- Message body recommended max: 4000 characters
- Rate-limit messaging to a reasonable rate per-user (for example, 10 messages/second burst limit and 1000/day combined) to prevent abuse. Return `429` when rate-limited.

Error codes (chat-specific)
- `USER_NOT_IN_SCOPE` - recipient is not in user's team or alliance
- `CONVERSATION_NOT_FOUND` - conversation id is invalid or inaccessible
- `MESSAGE_TOO_LONG` - message exceeds allowed length
- `RATE_LIMITED` - user exceeded messaging rate limits

Examples
--------

Send a direct message (curl example):

```bash
curl -X POST "https://your-server.com/api/mobile/chat/send" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"recipient_id":43, "body":"Meet at pit in 5"}'
```

Server implementers: enforce membership checks using the token payload (scouting_team_number) and the event/alliance membership tables. If your platform already has an alliances/connections table, reuse it to evaluate `alliance` scope.

---

## Events

### Get Events

Retrieve events for your scouting team.

**Endpoint:** `GET /api/mobile/events`

**Headers:**
```
Authorization: Bearer <token>
```

**Success Response (200):**
```json
{
  "success": true,
  "events": [
    {
      "id": 1,
      "name": "Greater Kansas City Regional",
      "code": "2024moks",
      "location": "Kansas City, MO",
      "start_date": "2024-03-14T00:00:00Z",
      "end_date": "2024-03-16T23:59:59Z",
      "timezone": "America/Chicago",
      "team_count": 45
    }
  ]
}
```

---

## Matches

### Get Matches

Retrieve matches for a specific event.

**Endpoint:** `GET /api/mobile/matches`

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters:**
- `event_id` (required) - Event ID
- `match_type` (optional) - Filter by match type (e.g., "Qualification")
- `team_number` (optional) - Filter by team number

**Success Response (200):**
```json
{
  "success": true,
  "matches": [
    {
      "id": 1,
      "match_number": 1,
      "match_type": "Qualification",
      "red_alliance": "5454,1234,5678",
      "blue_alliance": "9012,3456,7890",
      "red_score": 125,
      "blue_score": 110,
      "winner": "red"
    }
  ],
  "count": 1
}
```

---

## Scouting Data

### Submit Scouting Data

Submit new scouting data from mobile app.

**Endpoint:** `POST /api/mobile/scouting/submit`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "team_id": 1,
  "match_id": 5,
  "data": {
    "auto_speaker_scored": 3,
    "auto_amp_scored": 2,
    "teleop_speaker_scored": 10,
    "teleop_amp_scored": 5,
    "endgame_climb": "successful",
    "notes": "Great performance!"
  },
  "offline_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Success Response (201):**
```json
{
  "success": true,
  "scouting_id": 123,
  "message": "Scouting data submitted successfully",
  "offline_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Error Codes:**
- `MISSING_DATA`
- `MISSING_FIELD`
- `TEAM_NOT_FOUND`
- `MATCH_NOT_FOUND`
- `SUBMIT_ERROR`

Server processing (exact steps)
--------------------------------
The following describes exactly what the server does when it receives a scouting submission (single or bulk). This is intended to remove ambiguity for mobile clients and to make error handling deterministic.

Common requirements (single & bulk)
- The request must include an Authorization header: `Authorization: Bearer <token>`.
- The token is decoded and the `scouting_team_number` from the token payload is used to scope all data access.

Single submit (/scouting/submit) processing steps
1. Parse JSON body. If the body is missing or not JSON, return 400 `MISSING_DATA`.
2. Verify required fields exist: `team_id`, `match_id`, `data`. If any are missing return 400 `MISSING_FIELD` with the missing field name.
3. Convert `team_id` and `match_id` to integers if needed. If conversion fails treat as `TEAM_NOT_FOUND` / `MATCH_NOT_FOUND`.
4. Query the database: ensure `Team.id == team_id` and `Team.scouting_team_number == token.scouting_team_number`. If not found return 404 `TEAM_NOT_FOUND`.
5. Query the database: ensure `Match.id == match_id` and `Match.scouting_team_number == token.scouting_team_number`. If not found return 404 `MATCH_NOT_FOUND`.
6. Create a new `ScoutingData` record with fields populated as follows:
   - `team_id` = provided team_id
   - `match_id` = provided match_id
   - `data` = the `data` JSON object from the request (stored as JSON)
   - `scout` = the username (`request.mobile_user.username`) from the authenticated user
   - `scouting_team_number` = token.scouting_team_number
   - `timestamp` = current server time (UTC) unless the request explicitly provides a timestamp (bulk entries only support client timestamp, single uses server time)
7. Add the new record to the DB session and commit. If commit succeeds return 201 with `{ success: true, scouting_id: <id>, offline_id: <echoed if present> }`.
8. If any DB error or unexpected exception occurs the server rolls back the session and returns 500 `SUBMIT_ERROR`.

Bulk submit (/scouting/bulk-submit) processing steps
1. Parse JSON body and ensure it includes an `entries` array. If missing return 400 `MISSING_ENTRIES`.
2. The server processes each entry independently in order and builds a per-entry `results` array. For each entry:
   a. Validate required fields `team_id`, `match_id`, `data`. If missing, append a result with `offline_id`, `success: false`, and `error: 'Missing required fields'`.
   b. Verify `Team` and `Match` exist and belong to the authenticated scouting team (same checks as single submit). If not found append a failed result (`Team or match not found`).
   c. Parse `timestamp` if provided: the server accepts ISO 8601 timestamps. Implementation detail: the server uses `datetime.fromisoformat(timestamp.replace('Z', '+00:00'))` to parse UTC `Z`-terminated strings. If parsing fails, the server falls back to server current UTC time for that entry.
   d. Create a `ScoutingData` object with the same fields as single submit (but using the parsed client timestamp when provided).
   e. Add to DB session and call `db.session.flush()` to obtain the new row id without committing the transaction (this allows the server to include IDs in results while still validating all entries).
   f. If creation succeeds append `{ offline_id: entry.offline_id, success: true, scouting_id: <new id> }` to results; otherwise append failure with the exception message.
3. After processing all entries the server calls `db.session.commit()` to persist all successful entries in a single transaction. If commit raises an exception the server rolls back and returns 500 `BULK_SUBMIT_ERROR` with `success: false`.
4. The final response for bulk submit is 200 with a JSON body listing `submitted` (count of successful), `failed` (count of failed), and `results` (per-entry result objects). Entries that succeeded before an eventual commit failure may not be persisted (transactional semantics).

Exact timestamp behavior
- For single submissions the server sets the `timestamp` to current server UTC time (mobile clients should rely on server time for canonical timestamps unless they intentionally provide client timestamps in bulk entries).
- For bulk entries, if `timestamp` is provided in an entry, the server attempts to parse it as ISO 8601 (UTC `Z` is supported by replacing `Z` with `+00:00` before parsing). If parsing fails the server uses current UTC time for that entry.

Idempotency and `offline_id`
- `offline_id` is a client-provided identifier used to correlate local records with server results. The server echoes `offline_id` back in the single and bulk responses when present.
- The current implementation does not perform a global duplicate check by `offline_id` before insertion. Clients should use `offline_id` to deduplicate locally and should check server-side results before re-submitting.

Per-entry error object (bulk results)
- Successful entry example:
```json
{ "offline_id": "uuid-1", "success": true, "scouting_id": 123 }
```
- Failed entry example:
```json
{ "offline_id": "uuid-2", "success": false, "error": "Team or match not found" }
```

Server error responses (examples)
- Missing data (single):
  - HTTP 400
  - Body: { "success": false, "error": "No data provided", "error_code": "MISSING_DATA" }
- Missing field (single):
  - HTTP 400
  - Body: { "success": false, "error": "Missing required field: team_id", "error_code": "MISSING_FIELD" }
- Team not found:
  - HTTP 404
  - Body: { "success": false, "error": "Team not found", "error_code": "TEAM_NOT_FOUND" }
- Match not found:
  - HTTP 404
  - Body: { "success": false, "error": "Match not found", "error_code": "MATCH_NOT_FOUND" }
- Bulk transaction failure:
  - HTTP 500
  - Body: { "success": false, "error": "Failed to process bulk submission", "error_code": "BULK_SUBMIT_ERROR" }

Notes about images and large payloads
- Pit scouting images may be included as base64 strings in the `images` array of the pit scouting endpoint. For large images prefer a separate multipart upload endpoint (not implemented by default) to avoid very large JSON bodies.
- Keep bulk payload sizes moderate; the server processes entries in memory and a very large payload may fail.


### Bulk Submit Scouting Data

Submit multiple scouting entries at once (for offline sync).

**Endpoint:** `POST /api/mobile/scouting/bulk-submit`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "entries": [
    {
      "team_id": 1,
      "match_id": 5,
      "data": { "auto_speaker_scored": 3 },
      "offline_id": "uuid-1",
      "timestamp": "2024-01-01T12:00:00Z"
    },
    {
      "team_id": 2,
      "match_id": 6,
      "data": { "auto_speaker_scored": 5 },
      "offline_id": "uuid-2",
      "timestamp": "2024-01-01T12:05:00Z"
    }
  ]
}
```

**Success Response (200):**
```json
{
  "success": true,
  "submitted": 2,
  "failed": 0,
  "results": [
    {
      "offline_id": "uuid-1",
      "success": true,
      "scouting_id": 123
    },
    {
      "offline_id": "uuid-2",
      "success": true,
      "scouting_id": 124
    }
  ]
}
```

### Get Scouting History

Retrieve scouting history for the current user.

**Endpoint:** `GET /api/mobile/scouting/history`

**Headers:**
```
Authorization: Bearer <token>
```

**Query Parameters:**
- `limit` (optional, default: 50, max: 200) - Number of results
- `offset` (optional, default: 0) - Pagination offset

**Success Response (200):**
```json
{
  "success": true,
  "entries": [
    {
      "id": 123,
      "team_id": 1,
      "match_id": 5,
      "timestamp": "2024-01-01T12:00:00Z",
      "data": { "auto_speaker_scored": 3 }
    }
  ],
  "count": 1
}
```

---

## Pit Scouting

### Submit Pit Scouting Data

Submit pit scouting data for a team.

**Endpoint:** `POST /api/mobile/pit-scouting/submit`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "team_id": 1,
  "data": {
    "drive_train": "swerve",
    "weight": 120,
    "dimensions": "28x28x30",
    "autonomous_capabilities": ["speaker", "amp"],
    "notes": "Well-built robot"
  },
  "images": ["base64_encoded_image_1", "base64_encoded_image_2"]
}
```

**Success Response (201):**
```json
{
  "success": true,
  "pit_scouting_id": 456,
  "message": "Pit scouting data submitted successfully"
}
```

---

## Configuration

### Get Game Configuration

Retrieve current game configuration for mobile app. This endpoint now returns the full gameconfig JSON used by the web UI for the scouting team (not a trimmed subset). Mobile clients should expect the complete configuration including sections, rules, validation, and any custom fields.

**Endpoint:** `GET /api/mobile/config/game`

**Headers:**
```
Authorization: Bearer <token>
```

**Success Response (200):**
```json
{
  "success": true,
  "config": {
    "season": 2024,
    "game_name": "Crescendo",
    "alliance_size": 3,
    "match_types": ["Practice", "Qualification", "Playoff"],
    "scouting_form": {
      "sections": [
        {
          "name": "Autonomous",
          "elements": [
            {
              "id": "auto_speaker_scored",
              "type": "counter",
              "label": "Speaker Notes Scored",
              "min": 0,
              "max": 10
            }
          ]
        }
      ]
    },
    "current_event_code": "2024moks"
  }
}
```

How mobile apps should use the game configuration
-----------------------------------------------

The `/config/game` endpoint returns the full gameconfig JSON used by the web UI for your scouting team. The key field mobile clients will commonly use is `config.scouting_form` — it contains the sections and elements that define the fields shown on the web scouting form. By reading this structure, mobile apps can dynamically render the same form the web UI shows and keep behavior consistent across platforms.
Size and backward-compatibility note
----------------------------------
Because this endpoint returns the full gameconfig, payloads may be larger than the previous compact response. Mobile apps should cache the config and only re-fetch when `/sync/status` indicates updates or the server timestamp changes. If your client expects an older compact shape, read `config.scouting_form` and ignore extra fields — the server will continue to accept submissions that use the defined `id`s.


Scouting form contract (quick reference)
- `scouting_form.sections` — array of sections in the form. Each section has:
  - `name` (string): section title shown to the user
  - `elements` (array): list of element objects
- Each element object commonly includes:
  - `id` (string): unique identifier for the field used when submitting data
  - `type` (string): field type (see supported types below)
  - `label` (string): user-visible label
  - `help_text` (string, optional): short help description

---

### Notes: server-side image generation & fallback

- The mobile graphs endpoint tries to return a PNG image generated server-side using Plotly. If the server does not have a Plotly image engine available (for example, `kaleido`), the endpoint will instead return a JSON fallback with the Plotly figure under the key `fallback_plotly_json` so clients can render the chart themselves.

- To enable server-side PNG generation, install `kaleido` into the server environment and restart the app. Example addition to `requirements.txt`:

```
kaleido>=0.2.1
```

This provides a robust UX for mobile applications: either a ready-made PNG or a Plotly JSON that the client can render.

---

## Graph Image Endpoint

Generate chart images for teams (useful for mobile clients that want PNGs).

**Endpoint:** POST `/api/mobile/graphs`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request JSON (example):**
```json
{
  "team_number": 5454,
  "graph_type": "line",
  "metric": "total_points",
  "mode": "match_by_match"
}
```

**Response:**
- On success: HTTP 200 with Content-Type `image/png` and PNG bytes of the generated chart.
- On error: JSON with `success: false` and `error_code`.

Notes:
- The endpoint requires a valid mobile JWT token. Team isolation is respected (token's scouting_team_number).
- If the server lacks image-generation dependencies (kaleido or plotly image engines), the endpoint will return an error indicating the missing dependency.

  - `required` (boolean, optional): whether field is required
  - `default` (any, optional): default value
  - `options` (array, optional): for select/radio/checkbox types — list of {"value","label"}
  - `min`, `max` (number, optional): numeric limits for counters/sliders
  - `validation` (object, optional): regex or custom rules

Supported element types and recommended mobile UI mapping
- `counter` — integer counter, map to a stepper or numeric input (use `min`/`max`)
- `number` — numeric input, map to numeric keyboard and validation
- `text` — single-line text input
- `textarea` — multi-line text input
- `checkbox` — boolean toggle/switch
- `select` — single select dropdown
- `multi-select` / `checkbox-group` — multiple selection control
- `radio` — single-choice radio group (use `options`)
- `image` — image capture/upload (value is usually an image reference or base64 when submitted)
- `timestamp` / `datetime` — date/time picker
- `group` — a nested grouping of elements (the element's `elements` contains child fields)

Conditional visibility and client-side rules
------------------------------------------
The config may include optional `visibility` or `condition` rules for elements (for example, show field B only when field A has a certain value). Clients should evaluate these rules on the device and hide/disable fields accordingly. If no formal rule schema is provided, conservative handling is to render all fields and let the web server enforce stricter validation on submit.

Submitting scouting data that matches the form
---------------------------------------------
Mobile apps submit scouting answers to the existing endpoints (for example `/scouting/submit` or `/scouting/bulk-submit`). The `data` object you POST should use element `id`s as keys so server-side code can map answers to the form definition. Example:

Request body to `/api/mobile/scouting/submit`:
```json
{
  "team_id": 1,
  "match_id": 5,
  "data": {
    "auto_speaker_scored": 3,
    "auto_amp_scored": 2,
    "endgame_climb": "successful",
    "notes": "Great performance!"
  },
  "offline_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

JavaScript example: render form and submit
-----------------------------------------
This minimal example demonstrates how to fetch the config, render a simple form structure, and submit answers. It uses the `scouting_form.sections` layout and sends answers keyed by element `id`.

```javascript
// Fetch game config
const response = await fetch('https://your-server:8080/api/mobile/config/game', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { config } = await response.json();

// Build a simple in-memory form model
const formModel = {};
config.scouting_form.sections.forEach(section => {
  section.elements.forEach(elem => {
    formModel[elem.id] = elem.default ?? null;
  });
});

// Example: user updates a counter in the UI
formModel['auto_speaker_scored'] = 3;

// Submit answers
const submitResp = await fetch('https://your-server:8080/api/mobile/scouting/submit', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  },
  body: JSON.stringify({
    team_id: selectedTeamId,
    match_id: selectedMatchId,
    data: formModel,
    offline_id: generateUUID()
  })
});
const result = await submitResp.json();
if (!result.success) {
  // handle errors (validation, required fields, server errors)
}
```

Validation guidance
--------------------
- Respect `required` flags and client-side `min`/`max` limits when rendering inputs.
- Validate numeric ranges and option values before submitting. The server will validate again and return specific error codes if something is invalid.
- For image fields, upload images as base64 strings (if small) or implement a multipart image upload endpoint if your app needs large files; the current default is base64 in the request body under the element id.

Mapping to the web form
-----------------------
The web UI uses the same `scouting_form` definition to build its form. To provide parity between web and mobile:
- Render sections in the same order.
- Use the `label`, `help_text`, and `options` values for field UI.
- Keep field `id`s identical so submitted data maps the same way on the server.

Backward compatibility note
---------------------------
If the scouting form evolves during an event (fields added/removed), mobile clients should handle missing server-side fields gracefully: ignore unknown keys on fetch, and if a field is missing from the config, avoid submitting values for it. The server will validate and return helpful error codes on submit if required fields are missing.

---

## Sync

### Get Sync Status

Get sync status and server time.

**Endpoint:** `GET /api/mobile/sync/status`

**Headers:**
```
Authorization: Bearer <token>
```

**Success Response (200):**
```json
{
  "success": true,
  "server_time": "2024-01-01T12:00:00Z",
  "last_updates": {
    "teams": 42,
    "matches": 100
  }
}
```

---

## Health Check

### API Health Check

Check if the API is operational (no authentication required).

**Endpoint:** `GET /api/mobile/health`

**Success Response (200):**
```json
{
  "success": true,
  "status": "healthy",
  "version": "1.0",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

## Error Handling

All API endpoints return errors in a consistent format:

```json
{
  "success": false,
  "error": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE"
}
```

### Common HTTP Status Codes

- `200` - Success
- `201` - Created successfully
- `400` - Bad request (invalid input)
- `401` - Unauthorized (invalid or missing token)
- `404` - Not found
- `500` - Internal server error

### Common Error Codes

- `AUTH_REQUIRED` - Authentication token is missing
- `INVALID_TOKEN` - Token is invalid or expired
- `USER_NOT_FOUND` - User account not found
- `MISSING_DATA` - Required data missing from request
- `TEAM_NOT_FOUND` - Requested team not found
- `MATCH_NOT_FOUND` - Requested match not found
- `SUBMIT_ERROR` - Error submitting data
- `INTERNAL_ERROR` - Server error

---

## Mobile App Development Guide

### Authentication Flow

1. **Login** - Call `/auth/login` with username/password
2. **Store Token** - Save JWT token securely (Keychain/KeyStore)
3. **Include Token** - Add `Authorization: Bearer <token>` to all requests
4. **Refresh Token** - Call `/auth/refresh` periodically (before 7-day expiration)
5. **Handle Expiration** - If 401 received, prompt user to login again

### Offline Sync Strategy

1. **Queue Actions** - Store scouting submissions locally when offline
2. **Check Connectivity** - Monitor network status
3. **Bulk Sync** - When online, use `/scouting/bulk-submit` to upload queued data
4. **Track Offline IDs** - Use UUIDs to match server responses to local records
5. **Handle Conflicts** - Server responses indicate success/failure per entry

### Data Caching

1. **Cache Configuration** - Store game config locally, update periodically
2. **Cache Teams/Events** - Store team and event data for offline viewing
3. **Cache Matches** - Download match schedule for current event
4. **Periodic Refresh** - Update cached data when connected
5. **Sync Status** - Use `/sync/status` to check for updates

### Best Practices

1. **Handle Errors Gracefully** - Always check `success` field in responses
2. **Use Pagination** - Don't request too much data at once
3. **Respect Rate Limits** - Implement exponential backoff for retries
4. **Compress Images** - For pit scouting images, compress before upload
5. **Show Progress** - Provide user feedback during sync operations
6. **Security** - Never log or display JWT tokens
7. **Timestamps** - Always use ISO 8601 format with UTC timezone

### Example Mobile App Flow

```
1. User opens app
   ↓
2. Check if token exists and is valid
   ↓
3. If invalid/missing → Show login screen
   ↓
4. User logs in → Store token
   ↓
5. Load game config
   ↓
6. Download event/team/match data
   ↓
7. User scouts matches (online or offline)
   ↓
8. Sync data when connectivity available
   ↓
9. Refresh data periodically
```

---

## Sample Code

### JavaScript/React Native Example

```javascript
// Authentication
async function login(username, password) {
  const response = await fetch('https://your-server.com/api/mobile/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ username, password })
  });
  
  const data = await response.json();
  
  if (data.success) {
    // Store token securely
    await SecureStore.setItemAsync('auth_token', data.token);
    return data;
  } else {
    throw new Error(data.error);
  }
}

// Submit scouting data
async function submitScoutingData(teamId, matchId, scoutingData) {
  const token = await SecureStore.getItemAsync('auth_token');
  
  const response = await fetch('https://your-server.com/api/mobile/scouting/submit', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({
      team_id: teamId,
      match_id: matchId,
      data: scoutingData,
      offline_id: generateUUID()
    })
  });
  
  return await response.json();
}

// Offline sync
async function syncOfflineData(offlineEntries) {
  const token = await SecureStore.getItemAsync('auth_token');
  
  const response = await fetch('https://your-server.com/api/mobile/scouting/bulk-submit', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ entries: offlineEntries })
  });
  
  const result = await response.json();
  
  // Process results and update local database
  result.results.forEach(r => {
    if (r.success) {
      // Mark local entry as synced
      markAsSynced(r.offline_id, r.scouting_id);
    }
  });
  
  return result;
}
```

### Swift/iOS Example

```swift
// Authentication
func login(username: String, password: String) async throws -> LoginResponse {
    let url = URL(string: "https://your-server.com/api/mobile/auth/login")!
    
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    
    let body = ["username": username, "password": password]
    request.httpBody = try JSONEncoder().encode(body)
    
    let (data, response) = try await URLSession.shared.data(for: request)
    
    guard let httpResponse = response as? HTTPURLResponse,
          httpResponse.statusCode == 200 else {
        throw NetworkError.invalidResponse
    }
    
    let loginResponse = try JSONDecoder().decode(LoginResponse.self, from: data)
    
    // Store token in Keychain
    try KeychainHelper.save(loginResponse.token, forKey: "auth_token")
    
    return loginResponse
}

// Submit scouting data
func submitScoutingData(teamId: Int, matchId: Int, data: [String: Any]) async throws {
    let url = URL(string: "https://your-server.com/api/mobile/scouting/submit")!
    
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    
    // Get token from Keychain
    let token = try KeychainHelper.load(forKey: "auth_token")
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    
    let body: [String: Any] = [
        "team_id": teamId,
        "match_id": matchId,
        "data": data,
        "offline_id": UUID().uuidString
    ]
    
    request.httpBody = try JSONSerialization.data(withJSONObject: body)
    
    let (_, response) = try await URLSession.shared.data(for: request)
    
    guard let httpResponse = response as? HTTPURLResponse,
          httpResponse.statusCode == 201 else {
        throw NetworkError.submitFailed
    }
}
```

---

## Support

For questions or issues with the Mobile API:

1. Check the error code in the response
2. Verify authentication token is valid
3. Ensure all required fields are included
4. Check server logs for detailed error messages
5. Contact your system administrator

---

## Changelog

### Version 1.0 (2025)
- Initial release
- JWT authentication
- Team, event, and match endpoints
- Scouting data submission (single and bulk)
- Pit scouting support
- Game configuration endpoint
- Sync status endpoint
- Offline sync capabilities
