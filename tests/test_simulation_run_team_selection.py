from types import SimpleNamespace
from run import create_app
import json


def test_simulation_run_prefers_scoped_team(monkeypatch):
    # Create two team-like objects with same team_number but different ids
    t_preferred = SimpleNamespace(team_number=100, id=1, team_name='Preferred')
    t_other = SimpleNamespace(team_number=100, id=2, team_name='Other')

    # Patch get_team_by_number to return the preferred team
    import app.routes.simulations as sims
    monkeypatch.setattr(sims, 'get_team_by_number', lambda tn: t_preferred if tn == 100 else None)

    # Patch calculate_team_metrics to return different totals based on id
    def fake_calc(team_id, event_id=None, game_config=None):
        if team_id == 1:
            return {'metrics': {'total_points': 77}}
        elif team_id == 2:
            return {'metrics': {'total_points': 10}}
        return {'metrics': {}}

    monkeypatch.setattr(sims, 'calculate_team_metrics', fake_calc)

    app = create_app({'TESTING': True})
    with app.test_client() as c:
        resp = c.post('/simulations/run', json={'red': [100], 'blue': []})
        assert resp.status_code == 200
        data = resp.get_json()
        # expected_red should be ~77 (rounded)
        assert data['ok'] is True
        assert round(data['red']['expected_score']) == 77, f"Expected score to be ~77, got {data['red']['expected_score']}"
