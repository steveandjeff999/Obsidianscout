from app import create_app
from datetime import datetime, timezone

app = create_app()
with app.app_context():
    from app.models import Event
    from app.models_misc import NotificationQueue, NotificationSubscription

    event = Event.query.filter_by(code='MINOR').first()
    if not event:
        print('Event MINOR not found')
        exit(1)

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    q = NotificationQueue.query.join(
        NotificationSubscription, NotificationQueue.subscription_id == NotificationSubscription.id
    ).filter(
        NotificationSubscription.event_code == event.code,
        NotificationQueue.status == 'pending',
        NotificationQueue.scheduled_for > now_naive
    ).order_by(NotificationQueue.scheduled_for).limit(200).all()

    print('pending_count=', len(q))
    for n in q:
        print(n.id, n.subscription_id, n.match_id, n.scheduled_for)
