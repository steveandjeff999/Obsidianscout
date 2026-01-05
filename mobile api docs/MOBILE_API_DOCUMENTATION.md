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


### User Profile

Retrieve the authenticated mobile user's profile information including the profile picture path and a token-protected URL suitable for mobile clients to fetch.
Note: the profile picture URL returns a protected resource and requires the mobile JWT used to fetch the profile — include the `Authorization: Bearer <token>` header when requesting the picture.

**Endpoint:** `GET /api/mobile/profiles/me`

**Headers:**
```
Authorization: Bearer <token>
```

**Success Response (200):**
```json
{
  "success": true,
  "user": {
    "id": 42,
    "username": "scout123",
    "team_number": 5454,
    "profile_picture": "img/avatars/scout123.png",
    "profile_picture_url": "https://your-server.com/api/mobile/profiles/me/picture"  # protected; requires Authorization: Bearer <token>
  }
}
```

Errors:
- `401` - `AUTH_REQUIRED` (missing/invalid token)
- `500` - `PROFILE_ERROR` (internal server error)

**Error Codes:**
- `MISSING_CREDENTIALS`
- `INVALID_CREDENTIALS`
- `ACCOUNT_INACTIVE`

### Register (Create Account)

Create a new user account scoped to a scouting team. Teams may have account creation locked by an administrator; this endpoint will return `ACCOUNT_CREATION_LOCKED` in that case.

**Endpoint:** `POST /api/mobile/auth/register`

**Request Body:**
```json
{
  "username": "scout_new",
  "password": "securePass1",
  "confirm_password": "securePass1",  // optional, will be validated if provided
  "team_number": 5454,
  "email": "scout@example.com"        // optional
}
```

**Success Response (201):**
```json
{
  "success": true,
  "token": "eyJ...",
  "user": { "id": 99, "username": "scout_new", "team_number": 5454, "roles": ["scout"] },
  "expires_at": "2025-01-01T00:00:00Z"
}
```

**Error Responses:**
- `400` - `MISSING_FIELDS` or `PASSWORD_MISMATCH` or `INVALID_TEAM_NUMBER`
- `403` - `ACCOUNT_CREATION_LOCKED`
- `409` - `USERNAME_EXISTS` or `EMAIL_EXISTS`

### Refresh Token

Refresh an authentication token before it expires.

---

## Scouting Alliances (Collaboration)
Scouting alliances allow teams to collaborate by sharing scouting and pit data, inviting teams, and activating an alliance mode that adjusts what data is visible to alliance members.

> All Scouting Alliances endpoints require a valid Bearer token in the `Authorization` header.

### List my alliances and invitations
**Endpoint:** `GET /api/mobile/alliances`

**Headers:**
```
Authorization: Bearer <token>
```

**Success Response (200):**
```json
{
  "success": true,
  "my_alliances": [
    {
      "id": 8,
      "name": "Mobile Alliance",
      "description": "desc",
      "member_count": 2,
      "is_active": false,
      "config_status": "configured",
      "is_config_complete": true
    }
  ],
  "pending_invitations": [
    {
      "id": 4,
      "alliance_id": 8,
      "alliance_name": "Mobile Alliance",
      "from_team": 1111
    }
  ],
  "sent_invitations": [
    {
      "id": 5,
      "to_team": 2222,
      "alliance_id": 8,
      "alliance_name": "Mobile Alliance"
    }
  ],
  "active_alliance_id": null
}
```

### Create an alliance
**Endpoint:** `POST /api/mobile/alliances`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request:**
```json
{
  "name": "Mobile Alliance",
  "description": "Optional description"
}
```

**Success Response (200):**
```json
{ "success": true, "alliance_id": 8 }
```

### Send an invitation
**Endpoint:** `POST /api/mobile/alliances/{alliance_id}/invite`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request:**
```json
{ "team_number": 2222, "message": "Please join our alliance" }
```

**Success Response (200):**
```json
{ "success": true }
```

### Respond to an invitation
**Endpoint:** `POST /api/mobile/invitations/{invitation_id}/respond`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request:**
```json
{ "response": "accept" }  // or "decline"
```

**Success Response (200):**
```json
{ "success": true }
```

### Activate / Deactivate alliance mode
**Endpoint:** `POST /api/mobile/alliances/{alliance_id}/toggle`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request (activate):**
```json
{ "activate": true }
```

**Request (deactivate):**
```json
{ "activate": false, "remove_shared_data": true }
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Alliance mode activated for Mobile Alliance",
  "is_active": true
}
```

### Leave an alliance
**Endpoint:** `POST /api/mobile/alliances/{alliance_id}/leave`

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request (optional body):**
```json
{
  "remove_shared_data": false,   // If true, removes all shared data this team contributed to the alliance
  "copy_shared_data": false      // If true, copies shared alliance data back into the team's local tables before deactivation
}
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Successfully left the alliance \"Mobile Alliance\"",
  "alliance_deleted": false
}
```

**Notes:**
- Invitations returned in `pending_invitations` include `alliance_name` to simplify client UIs.
- When an alliance is deleted (last member leaves), pending invitations for that alliance are removed first to avoid FK/NOT NULL errors.
- If `copy_shared_data` is provided and true, the server will create local `ScoutingData` and `PitScoutingData` records for the leaving team by copying the relevant `AllianceSharedScoutingData` and `AllianceSharedPitData` entries before deactivating alliance mode.
- If `remove_shared_data` is provided and true, the server will delete the leaving team's shared entries from the alliance (useful when you want to purge your shared contributions). If both flags are set, copying occurs first, then shared entries are removed.
- Activating alliance mode may update the effective game/pit config and emits socket events (`alliance_mode_toggled`, `config_updated`) so clients can react in real time.

---

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

Mobile clients can inform the server which messages the user has read so the server can persist per-conversation read markers and keep `GET /api/mobile/chat/state` accurate (this updates the per-user chat state file used by the web UI as well). This is the recommended mobile-friendly endpoint.

Endpoint: `POST /api/mobile/chat/conversations/read`

Headers:
```
Authorization: Bearer <token>
Content-Type: application/json
```

Request Body (recommended shape):
```json
{
  "type": "dm" | "group" | "alliance",
  "id": "<username_or_group_or_alliance_id>",
  "last_read_message_id": "<message-id>"
}
```

Behavior:
- The server validates the caller's membership for the requested conversation (team membership for DMs/groups or alliance membership for alliance chats).
- The server writes a per-conversation last-read marker into the user's canonical chat state file (the server stores entries under `state['lastRead']` using keys like `"dm:alice"` or `"group:pit_team"`).
- When possible the server resolves the message timestamp and recomputes `state['unreadCount']` deterministically by scanning relevant DM/group history files; if message timestamps are unavailable the server performs a conservative update.
- The server persists the updated chat state to `instance/chat/users/<team_number>/chat_state_<normalized_username>.json` and emits a Socket.IO `conversation_read` event so other connected clients can update UI badges in real time.
- The endpoint is idempotent: posting the same `last_read_message_id` repeatedly does not change server state beyond the initial write.

Success Response (200):
```json
{ "success": true }
```

Legacy note:
- Older implementations also accept `POST /api/mobile/chat/conversations/{conversation_id}/read` with body `{ "last_read_message_id": <id> }`. The new form above is preferred for mobile clients because it explicitly declares conversation `type` and `id` and maps cleanly to the server's file-backed conversation model.


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

Chat state (unread count)
-------------------------

Mobile clients can poll a small, per-user chat state endpoint to obtain the current unread count and a light-weight pointer to the last message source. This is useful for keeping badges and notifications in sync without fetching full conversation histories.

Endpoint: `GET /api/mobile/chat/state`

Headers:
```
Authorization: Bearer <token>
```

Success response (200):
```json
{
  "success": true,
  "state": {
    "joinedGroups": ["main","pit_team"],
    "currentGroup": "main",
    "lastDmUser": "other_user",
    "unreadCount": 2,
    "lastSource": { "type": "dm", "id": "other_user" },
    "notified": true,
    "lastNotified": "2025-04-12T18:20:00+00:00"
  }
}
```

Notes:
- The endpoint reads the same per-user JSON used by the web UI: `instance/chat/users/<team_number>/chat_state_<normalized_username>.json`.
- `unreadCount` is the primary field mobile clients should use to update badges. The server ensures `unreadCount` is present and defaults it to 0 when no state file exists.
- `lastSource` is an optional pointer (e.g. `{ type: 'dm', id: '<username>' }`) that helps clients deep-link into the appropriate conversation when the user opens the app.
- This endpoint is read-only. To mark messages as read, use the existing web endpoints that reset unread state (the web UI calls `/chat/reset-unread`). Mobile clients may also call the equivalent mobile actions that modify per-user state via the chat send/edit endpoints when appropriate.

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

Optional fields supported by the server to help associate and deduplicate uploads:

- `event_id` (integer): associate this pit scouting entry with a specific Event (database id).
- `event_code` (string): alternative to `event_id`, resolved to an Event for the current scouting team (case-insensitive).
- `local_id` (string, UUID): a client-generated UUID used to deduplicate retries. If omitted the server will generate one.
- `device_id` (string): optional device identifier that created the entry.

Example including an event id and local_id:

```json
{
  "team_id": 73,
  "event_id": 5,
  "local_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "tablet-a-1",
  "data": {
    "team_name": "Team 73",
    "drive_team_experience": "experienced",
    "programming_language": "python",
    "drivetrain_type": "west_coast"
  }
}
```

Notes:
- If you want this entry to appear under a specific event in the web UI `/pit-scouting/list-dynamic`, include `event_id` (or `event_code`) in the upload request. The web listing shows entries associated with the current event or entries without an event_id (local-only data).
- Always include a `local_id` on the client when creating entries so retries don't create duplicates; the server will accept `local_id` and will return an existing record if it already exists for your scouting team.

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

Retrieve game configuration for mobile app. The mobile API now exposes multiple read endpoints to make the distinction explicit:

- **Active config (team or alliance):** `GET /api/mobile/config/game` and `GET /api/mobile/config/game/active` — returns the ``active`` configuration for the requester. If the requesting team's alliance mode is active and the alliance has a shared config, the active config will be the alliance-shared configuration; otherwise it is the team's explicit saved config.
- **Per-team explicit config file:** `GET /api/mobile/config/game/team` — returns the explicit saved per-team `game_config.json` (instance file) if present. This never merges alliance config and is useful for showing or downloading the raw team-level file.
- **Alliance shared config (by alliance id):** `GET /api/mobile/alliances/<alliance_id>/config/game` — returns the alliance's shared game configuration for the specified alliance if the requesting user is a member of that alliance (status `accepted`). This endpoint is designed to allow alliance members to fetch the alliance-shared configuration even when *their team has not activated alliance mode*; it requires a valid mobile JWT and membership in the alliance and will return `403 FORBIDDEN` if the caller is not a member.

All GET endpoints return the full gameconfig JSON used by the web UI (not a trimmed subset). Mobile clients should expect the complete configuration including sections, rules, validation, and any custom fields.

By default the server will attempt to return the team-level file from `instance/configs/<scouting_team_number>/game_config.json` when requested via `team`, otherwise the loader may return defaults or the alliance-shared JSON (when requesting `active`).

Examples:

- Fetch active config (may be alliance-shared if your team is active in an alliance):
```bash
curl -H "Authorization: Bearer $TOKEN" "https://your-server.com/api/mobile/config/game"
```

- Fetch alliance shared config by alliance id (requires alliance membership):
```bash
curl -H "Authorization: Bearer $TOKEN" "https://your-server.com/api/mobile/alliances/123/config/game"
```

### Set / Update Game Configuration

There are now two write endpoints to clearly separate editing of the active configuration vs. the explicit team file:

- **Active config (team or alliance):** `POST/PUT /api/mobile/config/game` and `POST/PUT /api/mobile/config/game/active` — Updates the active configuration for the requesting team. If the requesting team is in alliance mode and the alliance has a shared config, this endpoint will save to the alliance's `ScoutingAlliance.shared_game_config` and **requires the caller to be an alliance admin**. Otherwise it behaves as a team-save (admins may still use it to update their own team's config).

  **Note:** Mobile clients may now *read* alliance-shared configs directly by alliance id (see `GET /api/mobile/alliances/<alliance_id>/config/game`) even when the caller's team has not activated alliance mode. For **writing**:

  - If your team is in alliance mode, `POST/PUT /api/mobile/config/game` will save to the alliance's shared config (requires alliance-admin privileges).
  - If your team is *not* active but you are an **alliance admin** (accepted member with `role='admin'`) or a site `admin`/`superadmin`, you may update the alliance shared config directly using `POST/PUT /api/mobile/alliances/<alliance_id>/config/game` (new endpoint). This mirrors the web UI behavior that allows alliance admins to manage shared configs regardless of activation state.
- **Per-team config file:** `POST/PUT /api/mobile/config/game/team` — Updates the explicit per-team `game_config.json` file (team-only). This requires the caller to be a team `admin` or `superadmin`.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:** Raw JSON representing the full game configuration (same shape returned by GET `/api/mobile/config/game`). Example payload is identical to the GET response's `config` object.

**Success Response (200):**
```json
{
  "success": true
}
```

**Errors:**
- 401 / AUTH_REQUIRED: Missing or invalid token
- 403 / FORBIDDEN: Caller lacks admin permissions (or is not an alliance admin/member when calling alliance-specific endpoints)
- 400 / MISSING_BODY: Missing or invalid JSON payload
- 500 / SAVE_FAILED: Server failed to persist the configuration

- Notes:
- The server will persist per-team configuration when the authenticated admin belongs to a scouting team. If the caller is a global admin without a scouting team, the configuration is saved to the global `config/game_config.json` file.
- When saving to the "active" config while the team is in an active alliance and the alliance has a shared config, the endpoint will update the alliance shared config and **only alliance admins** may perform that operation. Attempting to edit the alliance shared config without alliance-admin privileges returns `403 FORBIDDEN`.
- If you want to update only your team file regardless of alliance mode, use `POST /api/mobile/config/game/team` instead.
 - If you want to update only your team file regardless of alliance mode, use `POST /api/mobile/config/game/team` instead.
 - Clients may pass `X-Mobile-Requested-Team: <team_number>` header or `?team_number=<team_number>` query parameter to operate on a specific team for this request; server permissions (admin, superadmin, or alliance-admin) will be checked for the requested team.
- The server performs minimal validation; consider validating keys client-side before sending. The web UI includes additional form-level validation.

Examples:

- Update active config (the server will save to alliance shared config if alliance active and you are an alliance admin; otherwise it saves to the team config):
```bash
curl -X PUT "https://your-server.com/api/mobile/config/game" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @new_game_config.json
```

- Update alliance shared config directly by alliance id (requires alliance admin or site admin; useful when your team is not active):
```bash
curl -X PUT "https://your-server.com/api/mobile/alliances/123/config/game" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @alliance_game_config.json
```

- Update explicit per-team file (always updates team file regardless of alliance mode):
```bash
curl -X PUT "https://your-server.com/api/mobile/config/game/team" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @team_game_config.json
```

### Get Pit Configuration

Retrieve pit configuration for mobile app. The mobile API now exposes multiple read endpoints:

- **Active config (team or alliance):** `GET /api/mobile/config/pit` and `GET /api/mobile/config/pit/active` — returns the active pit configuration (alliance's shared pit config if the token team is in alliance mode and alliance config present; otherwise the team's explicit config).
- **Per-team explicit config file:** `GET /api/mobile/config/pit/team` — returns the explicit per-team pit config file located at `instance/configs/<scouting_team_number>/pit_config.json` if present (no alliance merge).
- **Alliance shared pit config (by alliance id):** `GET /api/mobile/alliances/<alliance_id>/config/pit` — returns the alliance's shared pit configuration for the specified alliance if the requesting user is a member (`accepted`). This allows alliance members to fetch the shared pit configuration even when their team has not activated alliance mode; it requires authentication and alliance membership and will return `403 FORBIDDEN` if not a member.

Examples:

- Fetch active pit config:
```bash
curl -H "Authorization: Bearer $TOKEN" "https://your-server.com/api/mobile/config/pit"
```

- Fetch alliance shared pit config by alliance id (requires alliance membership):
```bash
curl -H "Authorization: Bearer $TOKEN" "https://your-server.com/api/mobile/alliances/123/config/pit"
```

- Update alliance shared pit config directly by alliance id (requires alliance admin or site admin; useful when your team is not active):
```bash
curl -X PUT "https://your-server.com/api/mobile/alliances/123/config/pit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @alliance_pit_config.json
```
### Set / Update Pit Configuration

Write endpoints for pit config mirror the game config endpoints:

**Note:** Mobile clients may fetch an alliance's shared pit config by alliance id (`GET /api/mobile/alliances/<alliance_id>/config/pit`) even when their team has not activated alliance mode, provided the caller is an accepted alliance member.

  - If your team is in alliance mode, `POST/PUT /api/mobile/config/pit` will save to the alliance's shared pit config (requires alliance-admin privileges).
  - If your team is *not* active but you are an **alliance admin** (accepted member with `role='admin'`) or a site `admin`/`superadmin`, you may update the alliance shared pit config directly using `POST/PUT /api/mobile/alliances/<alliance_id>/config/pit` (new endpoint). This mirrors the web UI behavior that allows alliance admins to manage shared configs regardless of activation state.

- **Active config (team or alliance):** `POST/PUT /api/mobile/config/pit` and `POST/PUT /api/mobile/config/pit/active` — Updates the active pit configuration. If in alliance mode and the alliance defines a shared pit config, this requires the caller to be an alliance admin and will persist to `ScoutingAlliance.shared_pit_config`.
- **Per-team config file:** `POST/PUT /api/mobile/config/pit/team` — Updates the per-team `pit_config.json` file. This requires the caller to be a team `admin` or `superadmin`.

**Headers:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:** Raw JSON representing the full pit configuration (same shape returned by GET `/api/mobile/config/pit`).

**Success Response (200):**
```json
{
  "success": true
}
```

**Errors:**
- 401 / AUTH_REQUIRED: Missing or invalid token
- 403 / FORBIDDEN: Caller lacks admin or alliance-admin permissions (see notes above)
- 400 / MISSING_BODY: Missing or invalid JSON payload
- 500 / SAVE_FAILED: Server failed to persist the configuration
 - 500 / SAVE_FAILED: Server failed to persist the configuration
 - Clients may pass `X-Mobile-Requested-Team: <team_number>` header or `?team=<team_number>` query parameter to operate on a specific team for this request; server permissions (admin, superadmin, or alliance-admin) will be checked for the requested team.

Examples:

- Update active pit config (alliance shared if active — requires alliance admin):
```bash
curl -X PUT "https://your-server.com/api/mobile/config/pit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @new_pit_config.json
```

- Update team pit config explicitly:
```bash
curl -X PUT "https://your-server.com/api/mobile/config/pit/team" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @team_pit_config.json
```

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

The `/config/game` endpoint returns the effective ("active") gameconfig JSON used by the web UI for your scouting team. Use `/config/game/active` (alias) to explicitly request the active config. The key field mobile clients will commonly use is `config.scouting_form` — it contains the sections and elements that define the fields shown on the web scouting form. For the raw saved per-team file, request `GET /api/mobile/config/game/team` (which returns the instance file if present). By reading `config.scouting_form` mobile apps can dynamically render the same form the web UI shows and keep behavior consistent across platforms.
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

### Visualizer Endpoint (Assistant-style PNGs)

A complementary endpoint is available that uses the server-side Assistant Visualizer (matplotlib-based) to produce PNG images of a wider set of visualization types. This is useful when mobile clients want a ready-made image instead of rendering Plotly JSON or generating charts locally.

Endpoint: `POST /api/mobile/graphs/visualize`

Headers:
```
Authorization: Bearer <token>
Content-Type: application/json
```

Request JSON (examples):
```json
{
  "vis_type": "team_performance",          // visualization types supported by the Visualizer
  "team_number": 5454,                      // single team OR
  "team_numbers": [5454, 1234],             // list of teams
  "visualization_data": { ... }             // optional: pre-built data payload matching the Visualizer's expectations
}
```

Behavior:
- If `visualization_data` is supplied the Visualizer will use it directly (this matches the assistant internal payload shape).
- If only team numbers are provided the server will compute basic metrics for the teams and construct a minimal `visualization_data` to pass to the Visualizer.
- The Visualizer supports types such as `team_performance`, `team_comparison`, `metric_comparison`, `match_breakdown`, `radar_chart`, `event_summary`, `match_schedule`, `team_ranking`, `ranking_comparison`, and `trend_chart`.

Compatibility note:
- This endpoint also accepts the full set of parameters supported by the Plotly-based `POST /api/mobile/graphs` endpoint (for example `graph_type`, `graph_types`, `metric`, `mode`, `event_id`, etc.). When the request payload contains Plotly-style keys the server will forward the request to the same handler used by `/api/mobile/graphs`, so you get identical behavior and the same PNG/fallback semantics. In other words, clients can use either `/api/mobile/graphs` or `/api/mobile/graphs/visualize` interchangeably for Plotly-style requests.

Responses:
- On success: HTTP 200 with Content-Type `image/png` and PNG bytes of the generated visualization.
- On failure: JSON with `{ "success": false, "error": "...", "error_code": "..." }` and an appropriate HTTP status.

Notes and dependencies:
- This endpoint uses the server-side `app.assistant.visualizer.Visualizer` which relies on `matplotlib` (Agg backend). Optional plotting libraries (`seaborn`, `pandas`, `numpy`) may improve styling but are not required for many plot types.
- If matplotlib or other required plotting libraries are missing the endpoint will return a JSON error indicating the missing dependency. For servers that prefer Plotly-based images, continue to use `POST /api/mobile/graphs` which uses Plotly and has a JSON fallback.

Security and scoping:
- The endpoint is JWT-protected and enforces the same team-isolation rules as other mobile endpoints. Requests that reference teams not accessible to the token's scouting_team_number will be ignored/skipped and may result in an error if no valid teams remain.

Example usage (curl):
```bash
curl -X POST "https://your-server.com/api/mobile/graphs/visualize" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"vis_type":"team_performance","team_number":5454}' --output team_5454.png
```

## JSON examples — Graphs

Copy-paste JSON examples for common graph requests and responses. These are the payloads to POST to `/api/mobile/graphs` or `/api/mobile/graphs/visualize` (when using Plotly-style parameters the visualize endpoint forwards to the same handler).

1) Plotly-style request (time-series / multi-team)

Request (POST /api/mobile/graphs or /api/mobile/graphs/visualize):
```json
{
  "team_numbers": [5454, 1234],
  "graph_type": "line",
  "metric": "total_points",
  "mode": "match_by_match",
  "event_id": 7
}
```

Successful server behavior:
- If the server can render PNGs (kaleido available) it returns HTTP 200 with Content-Type `image/png` and the PNG bytes in the body.
- If the server cannot render images, it returns HTTP 200 with JSON containing `fallback_plotly_json` (the Plotly figure JSON) so the client can render locally:

Example fallback JSON response (HTTP 200):
```json
{
  "success": true,
  "fallback_plotly_json": {
    "data": [ { "type": "scatter", "x": ["Match 1","Match 2"], "y": [45,52], "name": "5454" } ],
    "layout": { "title": "Total Points (match by match)" }
  }
}
```

2) Plotly-style request (bar of averages)

Request:
```json
{
  "team_numbers": [5454, 1234, 9012],
  "graph_type": "bar",
  "metric": "total_points",
  "mode": "averages"
}
```

Success: HTTP 200 `image/png` (or fallback JSON as above).

3) Visualizer-style request (Assistant Visualizer)

Request (POST /api/mobile/graphs/visualize):
```json
{
  "vis_type": "radar_chart",
  "team_numbers": [5454, 1234]
}
```

Success: HTTP 200 `image/png` with a matplotlib-generated image.

4) Visualizer with `visualization_data` (client-provided payload)

Request:
```json
{
  "vis_type": "team_performance",
  "visualization_data": {
    "team": {
      "number": 5454,
      "team_name": "Team 5454",
      "stats": {
        "total_points": 48,
        "auto_points": 12,
        "teleop_points": 30,
        "endgame_points": 6
      },
      "matches": [
        { "match_number": 1, "metric_value": 45 },
        { "match_number": 2, "metric_value": 52 }
      ]
    }
  }
}
```

Success: HTTP 200 `image/png` (Visualizer uses the supplied data directly).

5) Error responses (examples)

Missing teams / data (HTTP 400):
```json
{ "success": false, "error": "No team_number(s) or visualization_data provided", "error_code": "MISSING_TEAMS_OR_DATA" }
```

No teams resolved (HTTP 404):
```json
{ "success": false, "error": "No teams found", "error_code": "NO_TEAMS" }
```

Image-generation failure (HTTP 500):
```json
{ "success": false, "error": "Server cannot generate images (missing dependencies)", "error_code": "IMAGE_LIB_MISSING" }
```

Notes:
- When a PNG is returned the response body is raw bytes — not JSON. Clients should inspect the `Content-Type` header. If it starts with `image/` treat the body as an image. If it's `application/json` parse JSON and check for `fallback_plotly_json` or an error object.
- For easier debugging, run the `/api/mobile/auth/login` flow first and use the returned token in `Authorization: Bearer <token>` header for graph requests.

## Graph options & combinations (complete reference)

This section lists all supported parameters for the two graph/image endpoints and common combinations clients can use. Both endpoints accept JSON bodies and require a mobile JWT in `Authorization: Bearer <token>`.

Top-level parameters (shared between `/api/mobile/graphs` and `/api/mobile/graphs/visualize` when using Plotly-style payloads):

- `team_number` (int) — single team number (convenience for single-team charts). Optional when `team_numbers` is provided.
- `team_numbers` (array[int]) — list of team numbers to include. When provided, charts will include data for each of these teams (comparison charts, multi-line, radar, etc.).
- `event_id` (int or string code) — optional event id (or event code) used to scope match/scouting data for metrics.
- `graph_type` (string) — primary chart type. Supported values (Plotly route):
  - `line` — match-by-match time-series (lines + markers)
  - `bar` — bar chart (averages or totals)
  - `radar` — radar/polar comparison
  - `scatter` — scatter plot (points only)
  - `hist` / `histogram` — histogram (per-match value distribution)
  - `box` — box plot (per-team distribution with quartiles)
- `graph_types` (array[string]) — multiple graph types to return (compare endpoint uses this to return `line`, `bar`, `radar` payloads together).
- `metric` (string) — metric id to plot (examples below). Common metrics:
  - `total_points` / `points` / `tot` — total score per match or average total points
  - `auto_points` — autonomous phase points
  - `teleop_points` — teleop phase points
  - `endgame_points` — endgame/climb points
  - custom metric ids defined by your game's `gameconfig` (use the exact id)
- `mode` (string) — data mode for the chart:
  - `match_by_match` — plot each match's value in order (default for time-series)
  - `averages` — use per-team average values (useful for bar charts)
  - `aggregate` — aggregated totals across matches (if available)
- `data_view` (string) — high-level data shape requested (examples used in compare): `averages`, `per_match`, `totals`.
- `limit`, `offset` — pagination for endpoints that return dataset lists; not commonly used for image generation but accepted in some handlers.

Visualizer-specific parameters (Assistant Visualizer uses these when `vis_type` style requests are sent):

- `vis_type` (string) — visualization type for the Assistant Visualizer. Supported values:
  - `team_performance` — bar breakdown of Auto / Teleop / Endgame / Total for a single team
  - `team_comparison` — grouped bars comparing two or more teams
  - `metric_comparison` — horizontal bars for top teams by metric
  - `match_breakdown` — two-subplot match score comparison + phase breakdown
  - `radar_chart` — radar comparison for several core metrics
  - `event_summary` — multi-panel event summary (progress, coverage, timeline)
  - `match_schedule` — schedule visualization (horizontal rows per match)
  - `team_ranking` — ranked bar chart for a specific metric
  - `ranking_comparison` — compare ranking positions across metrics for a team
  - `trend_chart` — performance trend with regression/trend line
- `visualization_data` (object) — a pre-built payload shaped exactly as the Visualizer expects (for example the `visualization_data` returned by assistant responses). If present, the Visualizer will use it directly (this enables clients or server-side logic to compute series or stats and pass them in).

Metric/field notes and accepted values
- `metric` ids are case-sensitive strings matching either internal metric IDs (like `total_points`, `auto_points`) or custom metric keys from your `gameconfig.json`. Mobile clients should inspect `config.scouting_form` for available custom metric IDs if their game exposes them.
- Histogram responses return a `datasets` array with each team's `values`, `count`, and `mean`, plus top-level `total_samples`, `overall_mean`, and a `bin_suggestion` that mobile clients can use when constructing bins. When `graph_types` includes `"hist"`, the response contains both `histogram` and `hist` keys pointing to the same payload for convenience.
- Box plot responses include a `datasets` array where each entry provides the raw `values` along with a `stats` object (`count`, `min`, `max`, `median`, `q1`, `q3`).
- For `graph_type: radar` the Visualizer/Plotly handlers expect a small fixed label set (Total, Auto, Teleop, Endgame, Consistency (%)). For custom radar sets, use `visualization_data` to provide explicit labels and values.

Examples of useful combinations

1) Single-team trend image (Visualizer)

```json
{
  "vis_type": "trend_chart",
  "visualization_data": {
    "team_number": 5454,
    "match_scores": [ {"match_number":1, "score": 45}, {"match_number":2, "score": 52} ],
    "slope": 3.5,
    "intercept": 40
  }
}
```

2) Multi-team comparison (Plotly-style forwarded to `/api/mobile/graphs`):

```json
{
  "team_numbers": [5454, 1234],
  "graph_types": ["line","bar","radar"],
  "metric": "total_points",
  "event_id": 7
}
```

3) Bar chart of averages per team:

```json
{
  "team_numbers": [5454,1234,9012],
  "graph_type": "bar",
  "metric": "total_points",
  "mode": "averages"
}
```

4) Radar chart using Visualizer with server-computed metrics (preferred when you need normalized radar values):

```json
{
  "team_numbers": [5454,1234],
  "vis_type": "radar_chart"
}
```

Behavioral details and fallbacks
- If the server can produce PNG bytes (Plotly with kaleido or matplotlib available) the endpoint returns `Content-Type: image/png` and the PNG body.
- If Plotly image backends are not available, `/api/mobile/graphs` returns JSON containing `fallback_plotly_json` so clients can render the figure client-side. `/api/mobile/graphs/visualize` will attempt to fall back to the Plotly handler when Plotly-style parameters are sent; if neither Plotly nor matplotlib image rendering is available the Visualizer handler returns a JSON error.
- Team isolation: when requesting specific `team_numbers`, the server resolves Team records respecting the token's `scouting_team_number`. Unknown/unavailable teams are skipped; if no valid teams remain the request returns 404/empty-result.

Implementation notes for clients
- Prefer `team_numbers` when requesting multi-team charts. `team_number` is provided for convenience when requesting single-team charts.
- Use `visualization_data` for advanced or custom payload shapes — it is the most explicit and bypasses server-side metric aggregation.
- Use `graph_types` to request multiple chart variants in a single call (the `/graphs/compare` flow uses this pattern and the `/graphs` handler returns a JSON object containing each requested graph type when not returning a PNG).

If you'd like, I can also produce a small matrix table (CSV or markdown) enumerating every permutation of short common combos (e.g., single-team vs multi-team × line/bar/radar × match_by_match vs averages) for quick copy-paste samples.

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

### Trigger a Server Sync (Admin only)

Trigger a combined teams + matches sync (same behavior as the web/admin sync).

**Endpoint:** `POST /api/mobile/sync/trigger`

**Headers:**
```
Authorization: Bearer <token>
```

**Permissions:** Requires the mobile token's user to have `admin` or `analytics` role.

**Success Response (200):**
```json
{
  "success": true,
  "results": {
    "teams_sync": {"success": true, "message": "Teams sync attempted.", "flashes": []},
    "matches_sync": {"success": true, "message": "Matches sync attempted.", "flashes": []},
    "alliance_sync": {"triggered": false}
  }
}
```

**Errors:**
- `401` — invalid or missing token
- `403` — insufficient permissions
- `500` — server-side sync error


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
