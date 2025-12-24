import re
import json
import os

try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import Event, Match


def test_matches_event_param_honored():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # Create two events and a match for each
        e1 = Event(name='Current Event', code='CUR', year=2025)
        e2 = Event(name='Other Event', code='OTH', year=2025)
        db.session.add_all([e1, e2])
        db.session.commit()

        m1 = Match(match_number=1, match_type='Qualification', event_id=e1.id)
        m2 = Match(match_number=2, match_type='Qualification', event_id=e2.id)
        db.session.add_all([m1, m2])
        db.session.commit()

        # Simulate a global config that sets current_event_code to e1.code
        cfg_dir = os.path.join(os.getcwd(), 'config')
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, 'game_config.json')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump({'current_event_code': e1.code}, f)

        # Request the matches page with event_id set to e2 - should show matches for e2
        resp = client.get(f"/matches?event_id={e2.id}")
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # Ensure the option for e2 is present and marked selected
        pattern = rf'<option[^>]*value="{e2.id}"[^>]*selected'
        assert re.search(pattern, html), f"Event {e2.id} option was not selected in HTML:\n{html}"

        # Ensure the match from e2 is present in the page output
        assert '2' in html, f"Expected match number 2 for event {e2.id} not found in HTML:\n{html}"
