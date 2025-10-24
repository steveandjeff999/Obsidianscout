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
