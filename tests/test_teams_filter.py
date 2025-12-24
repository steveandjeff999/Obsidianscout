import re
import json
import os

try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import Event, Team


def test_teams_event_param_honored():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # Create two events and teams
        e1 = Event(name='Current Event', code='CUR', year=2025)
        e2 = Event(name='Other Event', code='OTH', year=2025)
        db.session.add_all([e1, e2])
        db.session.commit()

        t1 = Team(team_number=100, team_name='Alpha')
        t2 = Team(team_number=200, team_name='Beta')
        db.session.add_all([t1, t2])
        db.session.commit()

        # Associate teams to events
        t1.events.append(e1)
        t2.events.append(e2)
        db.session.commit()

        # Simulate a global config that sets current_event_code to e1.code
        cfg_dir = os.path.join(os.getcwd(), 'config')
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, 'game_config.json')
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump({'current_event_code': e1.code}, f)

        # Request the teams page with event_id set to e2 - should show teams for e2
        resp = client.get(f"/teams?event_id={e2.id}")
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # Ensure the option for e2 is present and marked selected
        pattern = rf'<option[^>]*value="{e2.id}"[^>]*selected'
        assert re.search(pattern, html), f"Event {e2.id} option was not selected in HTML:\n{html}"

        # Ensure the team from e2 is present in the page output and team from e1 is not
        assert '200' in html and '100' not in html, f"Expected team 200 to appear and 100 to be hidden for event {e2.id}:\n{html}"
