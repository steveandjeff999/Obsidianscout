import re

def test_sw_caches_graphs_pages():
    """Service worker should pre-cache the graphs dashboard and comparison pages."""
    sw_path = 'sw.js'
    with open(sw_path, 'r', encoding='utf-8') as f:
        data = f.read()
    # basic graph dashboard must be pre-cached
    assert '/graphs' in data, "Expected '/graphs' to be listed in STATIC_ASSETS"
    # side-by-side comparison is a distinct route – include that too
    assert '/graphs/side-by-side' in data, "Expected '/graphs/side-by-side' to be listed in STATIC_ASSETS"
    # settings page should be available offline
    assert '/settings' in data, "Expected '/settings' to be listed in STATIC_ASSETS"
    # ensure caching logic handles necessary data
    assert 'isGraphData' in data or '/graphs/data' in data, "Expected networkFirst to ignore or cache graph data"
    # the logic should also cache side-by-side or settings responses when fetched
    assert any(keyword in data for keyword in ['side-by-side','settings','isSideBySide','isSettings']), 
        "Expected networkFirst logic to recognise side-by-side or settings URLs"
