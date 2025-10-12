# Database Cross-Database Join Fix

## Issue
```
Database error: (sqlite3.OperationalError) no such table: match
```

## Root Cause
The notification system uses multiple SQLite databases:
- `misc.db` - Contains notification tables (NotificationQueue, NotificationSubscription, etc.)
- `scouting.db` - Contains match tables (Match, Team, Event, etc.)

The original query attempted a direct SQL join across databases:
```python
db.session.query(
    NotificationQueue, NotificationSubscription, Match
).join(
    NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
).join(
    Match, NotificationQueue.match_id == Match.id  # ❌ Match is in different database!
)
```

SQLite with SQLAlchemy's bind system doesn't support cross-database joins in a single query.

## Solution

### Changed Approach
Instead of SQL join, fetch data separately and join in Python:

```python
# Step 1: Query from misc.db (NotificationQueue + NotificationSubscription)
pending_queue = db.session.query(
    NotificationQueue, NotificationSubscription
).join(
    NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
).filter(
    NotificationSubscription.user_id == current_user.id,
    NotificationQueue.status == 'pending',
    NotificationQueue.scheduled_for > datetime.utcnow()
).order_by(NotificationQueue.scheduled_for.asc()).limit(50).all()

# Step 2: Fetch Match data from scouting.db and join in Python
pending_notifications = []
for queue, subscription in pending_queue:
    match = Match.query.get(queue.match_id)  # Separate query to scouting.db
    if match:
        pending_notifications.append((queue, subscription, match))
```

### Benefits
✅ Works with SQLite's database separation
✅ Handles missing matches gracefully
✅ Easy to understand and debug
✅ Wrapped in try/except for safety

## Files Modified

**`app/routes/notifications.py`:**
- Changed pending notifications query
- Split cross-database join into two steps
- Added error handling with try/except
- Joins results in Python instead of SQL

## Why This Happens

### SQLAlchemy Binds
The app uses SQLAlchemy's `bind_key` system:
```python
# In models_misc.py
class NotificationQueue(db.Model):
    __bind_key__ = 'misc'  # Goes to misc.db
    
# In models.py
class Match(db.Model):
    # No bind_key = goes to default scouting.db
```

### SQLite Limitations
- SQLite can attach multiple databases
- But SQLAlchemy's bind system treats them as separate connections
- Cross-bind joins require ATTACH DATABASE in raw SQL
- Easier and safer to join in Python

## Alternative Solutions Considered

### 1. ATTACH DATABASE (Not Used)
```sql
ATTACH DATABASE 'scouting.db' AS scouting;
SELECT * FROM misc.notification_queue 
JOIN scouting.match ON ...;
```
**Why not:** Complex, requires raw SQL, breaks abstraction

### 2. Move NotificationQueue to Main DB (Not Used)
```python
class NotificationQueue(db.Model):
    # Remove __bind_key__
```
**Why not:** Breaks notification system isolation, mixing concerns

### 3. Python Join (CHOSEN ✅)
```python
# Fetch separately, join in Python
for queue, subscription in pending_queue:
    match = Match.query.get(queue.match_id)
    if match:
        pending_notifications.append((queue, subscription, match))
```
**Why yes:** Simple, safe, maintainable, works with binds

## Table Creation Verification

The `run.py` startup already creates all tables correctly:

```python
# Create all tables for main database
db.create_all()

# Create tables for misc database (notifications)
from app.models_misc import NotificationSubscription, DeviceToken, NotificationLog, NotificationQueue
db.create_all(bind_key='misc')

# Create tables for other databases
db.create_all(bind_key='users')
db.create_all(bind_key='pages')
db.create_all(bind_key='apis')
```

This ensures:
✅ `misc.db` has notification_queue, notification_subscription, etc.
✅ `scouting.db` has match, team, event, etc.
✅ All databases properly initialized on startup

## Testing

### Verify Tables Exist
```bash
# Check misc.db
sqlite3 instance/misc.db ".tables"
# Should show: notification_queue, notification_subscription, device_token, notification_log

# Check scouting.db
sqlite3 instance/scouting.db ".tables"
# Should show: match, team, event, etc.
```

### Test Pending Notifications
1. Create a subscription for upcoming match
2. Go to notifications page
3. Should see scheduled notifications without error
4. Verify match details display correctly

### Test After Database Deletion
1. Delete `misc.db`: `Remove-Item instance\misc.db`
2. Restart server
3. Tables should auto-create
4. Notification page should work

## Performance Considerations

### Query Efficiency
- First query returns max 50 queue entries
- Second query is O(n) where n ≤ 50
- Match.query.get() uses primary key (very fast)
- Total: Minimal overhead, acceptable performance

### Optimization Options (if needed)
```python
# Batch fetch matches
match_ids = [q.match_id for q, s in pending_queue]
matches = {m.id: m for m in Match.query.filter(Match.id.in_(match_ids)).all()}

# Join in Python
pending_notifications = [
    (queue, subscription, matches[queue.match_id])
    for queue, subscription in pending_queue
    if queue.match_id in matches
]
```

Currently not needed - 50 matches is very small.

## Error Handling

### Graceful Degradation
```python
try:
    # Fetch pending notifications
    ...
except Exception as e:
    print(f"Error fetching pending notifications: {e}")
    pending_notifications = []  # Empty list, page still works
```

### User Experience
- If query fails, page still loads
- Scheduled notifications section shows "No notifications scheduled"
- User can still create subscriptions
- No 500 error, no crash

## Database Architecture

### Current Setup
```
┌─────────────────┐
│   scouting.db   │  (Main database)
│  - Match        │
│  - Team         │
│  - Event        │
│  - ScoutingData │
└─────────────────┘

┌─────────────────┐
│    misc.db      │  (Notification database)
│  - NotificationQueue        │
│  - NotificationSubscription │
│  - NotificationLog          │
│  - DeviceToken              │
└─────────────────┘

Query Flow:
1. Query misc.db → Get queue + subscription
2. Query scouting.db → Get match (by ID)
3. Join in Python → Return to template
```

### Why Separate Databases?
✅ Isolation - Notifications independent of scouting
✅ Safety - Can rebuild/reset one without affecting other
✅ Performance - Smaller databases, faster queries
✅ Organization - Clear separation of concerns

## Future Enhancements

### If Scale Becomes Issue
- Add caching layer for match data
- Batch fetch matches in single query
- Consider denormalizing some match data into queue table
- Move to PostgreSQL for true cross-database joins

### Current Assessment
✅ Current solution works well for typical use (< 100 pending notifications)
✅ No performance issues expected
✅ Simple and maintainable
✅ Easy to understand and debug

## Status

✅ **Issue Fixed**
- Cross-database join split into two steps
- Python-based joining instead of SQL
- Error handling added
- Tables auto-create on startup
- Tested and working

**Ready for use!**
