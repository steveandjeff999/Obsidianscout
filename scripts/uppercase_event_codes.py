"""One-off script to uppercase existing event codes in the database.

Run with the project venv activated from repo root:

"""

from app import create_app, db
from app.models import Event, ScoutingAllianceEvent

app = create_app()

with app.app_context():
    try:
        print('Uppercasing Event.code entries...')
        updated = 0
        for ev in Event.query.filter(Event.code.isnot(None)).all():
            if isinstance(ev.code, str) and ev.code != ev.code.upper():
                ev.code = ev.code.upper()
                updated += 1
        db.session.commit()
        print(f'Updated {updated} Event records')
    except Exception as e:
        db.session.rollback()
        print('Error updating Event records:', e)

    try:
        print('Uppercasing ScoutingAllianceEvent.event_code entries...')
        updated2 = 0
        for ae in ScoutingAllianceEvent.query.filter(ScoutingAllianceEvent.event_code.isnot(None)).all():
            if isinstance(ae.event_code, str) and ae.event_code != ae.event_code.upper():
                ae.event_code = ae.event_code.upper()
                updated2 += 1
        db.session.commit()
        print(f'Updated {updated2} ScoutingAllianceEvent records')
    except Exception as e:
        db.session.rollback()
        print('Error updating AllianceEvent records:', e)

    print('Done')
