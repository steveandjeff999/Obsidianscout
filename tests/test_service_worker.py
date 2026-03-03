import re

def test_sw_caches_graphs_page():
    """Service worker should pre-cache the graphs page so offline /graphs works."""
    sw_path = 'sw.js'
    with open(sw_path, 'r', encoding='utf-8') as f:
        data = f.read()
    assert '/graphs' in data, "Expected '/graphs' to be listed in STATIC_ASSETS"
    # ensure caching logic handles JSON
    assert 'isGraphData' in data or '/graphs/data' in data, "Expected networkFirst to ignore or cache graph data"
