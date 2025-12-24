from types import SimpleNamespace
from app.routes import simulations
from run import create_app


def test_simulations_dedupe(monkeypatch):
    # Create two team-like objects with the same team_number
    t1 = SimpleNamespace(team_number=100, team_name='LocalTeam', events=[])
    t2 = SimpleNamespace(team_number=100, team_name='OtherTeam', events=[])

    # Patch the filter_teams_by_scouting_team to return both records
    monkeypatch.setattr(simulations, 'filter_teams_by_scouting_team', lambda *a, **k: [t1, t2])

    app = create_app({'TESTING': True})
    with app.test_client() as c:
        resp = c.get('/simulations/')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Count occurrences of this team number in the team list
        occurrences = html.count('data-team-number="100"')
        # Expect only one occurrence after deduplication
        assert occurrences == 1, f"Expected 1 occurrence of team 100, found {occurrences}"
