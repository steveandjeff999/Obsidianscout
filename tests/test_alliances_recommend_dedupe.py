from app import create_app, db
from app.models import Event, Team
import app.routes.alliances as alliances_mod


def test_recommendations_dedupes_teams(tmp_path):
    app = create_app()
    with app.app_context():
        # Create sample event and team
        ev = Event(name='Dedupe Event', code='DEDUPE', year=2025)
        t = Team(team_number=1111, team_name='Team 1111')
        db.session.add_all([ev, t])
        db.session.commit()

        # Create a fake query object that returns duplicate team entries
        class FakeQuery:
            def join(self, *args, **kwargs):
                return self
            def filter(self, *args, **kwargs):
                return self
            def order_by(self, *args, **kwargs):
                return self
            def all(self):
                # Return the same team object twice to simulate duplicate rows from join
                return [t, t]

        orig = alliances_mod.filter_teams_by_scouting_team
        try:
            alliances_mod.filter_teams_by_scouting_team = lambda: FakeQuery()
            client = app.test_client()
            resp = client.get(f'/alliances/recommendations/{ev.id}')
            assert resp.status_code == 200
            data = resp.get_json()
            # Ensure returned list deduplicated
            ids = [entry['team']['id'] for entry in data.get('recommendations', [])]
            assert len(ids) == len(set(ids))
        finally:
            alliances_mod.filter_teams_by_scouting_team = orig
