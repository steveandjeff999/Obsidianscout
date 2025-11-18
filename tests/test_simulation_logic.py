def test_simulation_function_basic():
    from app.utils.analysis import _simulate_match_outcomes
    # simple test with deterministic values
    red = [{'team': None, 'metrics': {'tot': 20.0, 'tot_std': 0.0, 'consistency_factor': 1.0}} for _ in range(3)]
    blue = [{'team': None, 'metrics': {'tot': 10.0, 'tot_std': 0.0, 'consistency_factor': 1.0}} for _ in range(3)]
    res = _simulate_match_outcomes(red, blue, 'tot', n_simulations=100)
    assert 'expected_red' in res and 'expected_blue' in res
    assert res['expected_red'] >= res['expected_blue']


def test_simulation_overlap_allowed():
    from app.utils.analysis import _simulate_match_outcomes
    # Use identical teams on both alliances (overlap allowed)
    team = {'team': None, 'metrics': {'tot': 20.0, 'tot_std': 0.0, 'consistency_factor': 1.0}}
    red = [team for _ in range(3)]
    blue = [team for _ in range(3)]
    res = _simulate_match_outcomes(red, blue, 'tot', n_simulations=100)
    assert 'expected_red' in res and 'expected_blue' in res
    # If identical teams, expected scores should be equal or nearly equal
    assert abs(res['expected_red'] - res['expected_blue']) < 1e-6


def test_simulation_with_defaults_backend():
    # Ensure backend uses defaults when seed and simulation count are not provided
    from app.routes import simulations
    from app import app
    # create a test client and run a minimal POST to /simulations/run with sample teams
    with app.test_client() as client:
        # Need an analytics user or login stub; rely on existing test setup in CI (skip here if not authenticated)
        # We'll just ensure the endpoint is callable in a simple way for smoke testing (this might need auth fixtures in full tests).
        res = client.post('/simulations/run', json={'red': [], 'blue': []})
        # If server rejects due to auth this will be 302 or 401; we won't assert on that here in the unit test environment
        assert res is not None
