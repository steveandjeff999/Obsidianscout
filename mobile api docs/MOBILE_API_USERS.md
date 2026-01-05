# Mobile API - User Management (Admin)

This document describes mobile endpoints for administrative management of users. These endpoints require a token with an `admin` role (or `superadmin`). Team-scoped admins (`admin`) may only manage users within their team; `superadmin` may manage any user and change username/team.

Endpoints:
- GET /api/mobile/admin/roles
- GET /api/mobile/admin/users
- POST /api/mobile/admin/users
- GET /api/mobile/admin/users/<user_id>
- PUT /api/mobile/admin/users/<user_id>
- DELETE /api/mobile/admin/users/<user_id>

Headers:
```
Authorization: Bearer <token>
Content-Type: application/json
```

Request body (JSON, all fields optional):
- `username` (string) - New username (superadmin only)
- `email` (string|null) - New email (set to `null` to clear)
- `scouting_team_number` (int|null) - New team (superadmin only)
- `password` (string) - New password for the user
- `is_active` (bool) - Set active/deactivated flag
- `roles` (array[string]) - List of role names to assign (e.g., ["scout", "admin"]). Team admins may not assign the `superadmin` role.

Example request:
```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "newpass",
  "is_active": true,
  "roles": ["scout", "admin"]
}
```

Responses:
- 200 (OK):
```json
{
  "success": true,
  "user": {
    "id": 123,
    "username": "alice",
    "email": "alice@example.com",
    "team_number": 5454,
    "roles": ["scout", "admin"],
    "is_active": true
  }
}
```

- 401 (Unauthorized): Missing or invalid token.
- 403 (Forbidden): Permission denied (e.g., non-admin or team-admin trying to modify outside their team).
- 404 (Not Found): User not found.
- 409 (Conflict): Username or email already taken.
- 500 (Server Error): Unexpected error.

Notes:
- Team admins cannot assign or remove the `superadmin` role and cannot change username or team membership.
- Team admins cannot modify other `superadmin` accounts.
- Users cannot modify their own roles unless they are `superadmin`.
- Roles are expected as a list of role names (strings). Use the `roles` endpoint on web to list available roles if needed.

The mobile API provides create and delete endpoints as listed above. Below are brief details for each.

GET /api/mobile/admin/roles
- Headers: Authorization: Bearer <token>
- Returns list of roles: {"success": true, "roles": [{"id":1, "name":"admin", "description":"..."}]}

GET /api/mobile/admin/users
- Optional query param `search` (username or team number).
- Optional query param `include_inactive` (boolean): set `1`/`true`/`yes` to include deactivated users; default is to exclude them.
- Scoped to token's `team_number` unless `superadmin`.

POST /api/mobile/admin/users
- Create a new user. JSON body same as web `add_user` (username, password, email, scouting_team_number (superadmin only), roles).
- Returns 201 and the created user record.

GET /api/mobile/admin/users/<user_id>
- Return user details (scoped to team unless superadmin).

DELETE /api/mobile/admin/users/<user_id>
- Permanently delete a user (hard delete). This will remove the user account and clear device and notification subscriptions. Scouting/pit data and message history will be anonymized where possible (scout_id, sender_id, recipient_id set to null). This action is irreversible.
