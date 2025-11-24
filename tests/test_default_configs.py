import os
from app.utils.config_manager import get_available_default_configs, load_default_config


def test_default_configs_present():
    configs = get_available_default_configs()
    assert isinstance(configs, list)
    # We expect at least one game and one pit config across years
    types = {c['type'] for c in configs}
    assert 'game' in types
    assert 'pit' in types
    # Each entry should expose a basename for UI display
    for c in configs:
        assert 'basename' in c


def test_load_default_config():
    configs = get_available_default_configs()
    assert configs
    # Try loading the first two configs (if available)
    for cfg in configs[:2]:
        data = load_default_config(cfg['filename'])
        assert isinstance(data, dict)