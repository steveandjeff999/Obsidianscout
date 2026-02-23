import os


def test_countup_help_text_contains_reduced_motion_note():
    """The settings page should tell users that the count‑up toggle is overridden by
    the reduced‑motion preference."""
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, 'app', 'templates', 'settings.html')
    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()
    assert 'overridden when "Reduce motion" is enabled' in html


def test_countup_js_respects_reduced_motion():
    """The site JS should refuse to animate when reduced‑motion is set."""
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, 'app', 'static', 'js', 'countup-site.js')
    with open(path, 'r', encoding='utf-8') as f:
        js = f.read()
    # look for the check added in isCountupEnabled
    assert 'localStorage.getItem' in js
    assert 'reduced_motion' in js
    assert 'isCountupEnabled' in js
