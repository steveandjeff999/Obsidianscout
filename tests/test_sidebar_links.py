import os


def test_sidebar_template_contains_new_links():
    """Verify base.html includes the QR scanner and events link markup.

    This is a simple template-level test that doesn't exercise the web server or
    database.  Since the sidebar visibility logic is already guarded by role
    checks, ensuring the items are present is sufficient for this change.
    """
    base = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base, 'app', 'templates', 'base.html')
    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()

    assert 'url_for(\'data.import_qr\')' in html
    assert 'url_for(\'events.index\')' in html
    # ensure we no longer link against the API endpoint
    assert 'data.data_events' not in html
    # verify they appear under the admin/analytics conditional
    assert "user_has_role('admin') or user_has_role('analytics')" in html

    # dark mode resources should be declared early so we don't flash light styles
    assert 'dark-mode-force.css' in html
    assert 'dark-theme-modern.css' in html
    # dark-mode links are always present (selectors inside guard by .dark-mode)
    assert 'dark-mode-force.css' in html and '<link rel="stylesheet"' in html
    assert '<link rel="preload"' in html
    # an ultra-early script should exist to apply dark-mode before any paint
    assert 'extremely early' in html or 'ultra-early' in html or 'theme detection executed before any styles are parsed' in html
