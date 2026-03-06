import os
import json

try:
    from app import create_app, db
    import app.routes.teams as teams_routes
except Exception:
    create_app = None
    db = None
    teams_routes = None

from app.models import Team


def test_participating_events_year_from_config(monkeypatch):
    """When a season/year is set in game_config, the team view should use it.

    The view header and "no events" message should both reflect the value, and
    the API call should be invoked with that year.
    """
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # prepare a fake team
        t = Team(team_number=1234, team_name="Test")
        db.session.add(t)
        db.session.commit()

        # set configuration to a non-current year
        cfg_dir = os.path.join(os.getcwd(), "config")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, "game_config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"season": 2026}, f)

        # monkeypatch the TBA API helper so we can observe the year passed
        captured = {}

        def fake_get_tba(team_key, year=None):
            captured['year'] = year
            return []

        monkeypatch.setattr(teams_routes, "get_tba_team_events", fake_get_tba)

        resp = client.get("/teams/1234/view")
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')

        # header should show the configured year
        assert "Participating Events (2026)" in html
        # alert message also uses the same year
        assert "No events found for this team in 2026" in html
        # our stub should have been called with 2026
        assert captured.get('year') == 2026
