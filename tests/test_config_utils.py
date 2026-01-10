from app.routes.main import ensure_complete_config_structure


def test_none_input_returns_defaults():
    cfg = ensure_complete_config_structure(None)
    assert isinstance(cfg, dict)
    # Basic defaults
    assert 'game_name' in cfg
    assert 'season' in cfg
    assert 'auto_period' in cfg
    assert isinstance(cfg['auto_period'].get('scoring_elements', []), list)


def test_existing_config_preserved():
    input_cfg = {
        'game_name': 'Test Game',
        'auto_period': {'duration_seconds': 10, 'scoring_elements': []},
        'season': 2022
    }
    out = ensure_complete_config_structure(input_cfg)
    assert out['game_name'] == 'Test Game'
    assert out['season'] == 2022
    assert out['auto_period']['duration_seconds'] == 10
    assert isinstance(out['teleop_period']['scoring_elements'], list)
