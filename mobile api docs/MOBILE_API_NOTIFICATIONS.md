# Mobile API - Scheduled Notifications

This document describes the mobile endpoint that returns pending scheduled notifications for a scouting team.

Endpoint: GET /api/mobile/notifications/scheduled

Headers:
```
Authorization: Bearer <token>
```

Query parameters (optional):
- limit (int) - max results (default 200, max 1000)
- offset (int) - pagination offset (default 0)

Response (200):
```json
{
  "success": true,
  "count": 1,
  "total": 12,
  "notifications": [
    {
      "id": 123,
      "subscription_id": 5,
      "notification_type": "match_reminder",
      "match_id": 10,
      "match_number": 3,
      "event_id": 7,
      "event_code": "CALA",
      "scheduled_for": "2025-04-12T18:20:00+00:00",
      "status": "pending",
      "attempts": 0,
      "delivery_methods": {"email": true, "push": true},
      "target_team_number": 5454,
      "minutes_before": 20,
      "weather": null
    }
  ]
}
```

Notes:
- `delivery_methods` indicates which channels are enabled on the subscription (email and/or push).
- `weather` is returned as `null` by default. Server-side weather integration is optional; clients may fetch weather for scheduled times/locations if they need a forecast.
- Results are scoped to the token's `team_number` (data isolation).

## Combined “unread” view

A convenience endpoint that returns both the mobile chat state (including
`unreadCount` and optional `unreadMessages`) and the list of pending scheduled
notifications. Clients can use this single call instead of fetching `/chat/state`
and `/notifications/scheduled` separately.

Endpoint: GET /api/mobile/notifications/unread

Headers:
```
Authorization: Bearer <token>
```

Query parameters (optional):
- limit (int) - max scheduled notifications to fetch (default 200, max 1000)
- offset (int) - pagination offset for the scheduled list (default 0)

Response (200):
```json
{
  "success": true,
  "chat_state": { /* same structure as /chat/state */ },
  "scheduled": {
      "count": 1,
      "total": 12,
      "notifications": [ /* as /notifications/scheduled */ ]
  }
}
```


Past notifications (sent history)
--------------------------------

Endpoint: GET /api/mobile/notifications/past

Headers:
```
Authorization: Bearer <token>
```

Query parameters (optional):
- limit (int) - max results (default 200, max 1000)
- offset (int) - pagination offset (default 0)

Response (200):
```json
{
  "success": true,
  "count": 1,
  "total": 12,
  "notifications": [
    {
      "id": 123,
      "subscription_id": 5,
      "notification_type": "match_reminder",
      "match_id": 10,
      "match_number": 3,
      "event_code": "CALA",
      "sent_at": "2025-04-12T18:20:00+00:00",
      "email_sent": true,
      "push_sent_count": 2,
      "email_error": null,
      "push_error": null,
      "title": "Match reminder",
      "message": "Match 3 coming up in 20 minutes",
      "target_team_number": 5454
    }
  ]
}
```

Notes:
- Results are returned in descending send time (most recent first) and scoped to the token's `team_number`.
- `email_sent` is a boolean; `push_sent_count` is the number of devices successfully notified.
- If you want additional filters (by event, match, or time range), tell me and I can add them.
