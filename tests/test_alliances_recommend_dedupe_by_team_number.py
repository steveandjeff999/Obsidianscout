from app import create_app, db
from app.models import Event, Team
import app.routes.alliances as alliances_mod


def test_recommendations_dedupes_by_team_number(tmp_path):
    app = create_app()
    with app.app_context():
        # Create sample event and two different Team rows with same team number
        ev = Event(name='Dedupe Event 2', code='DEDUPE2', year=2025)
        t1 = Team(team_number=2357, team_name='Team A')
        t2 = Team(team_number=2357, team_name='Team B (duplicate)')
        db.session.add_all([ev, t1, t2])
        db.session.commit()

        # Fake query that returns both different Team objects (different ids but same team_number)
        class FakeQuery:
            def join(self, *args, **kwargs):
                return self
            def filter(self, *args, **kwargs):
                return self
            def order_by(self, *args, **kwargs):
                return self
            def all(self):
                return [t1, t2]

        orig = alliances_mod.filter_teams_by_scouting_team
        try:
            alliances_mod.filter_teams_by_scouting_team = lambda: FakeQuery()
            client = app.test_client()
            resp = client.get(f'/alliances/recommendations/{ev.id}')
            assert resp.status_code == 200
            data = resp.get_json()
            ids = [entry['team']['id'] for entry in data.get('recommendations', [])]
            # Team number 2357 should only appear once (ids set may contain either t1.id or t2.id)
            assert len([t for t in ids if t in (t1.id, t2.id)]) == 1
        finally:
            alliances_mod.filter_teams_by_scouting_team = orig
