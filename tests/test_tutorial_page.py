def test_tutorial_page_renders(client):
    """Tutorial hub renders and offers both tutorial choices."""
    resp = client.get('/setup/tutorial')
    assert resp.status_code == 200
    body = resp.data
    assert b'Tutorial Hub' in body
    assert b'Open Scout Tutorial' in body
    assert b'Open Analytics Tutorial' in body


def test_scout_tutorial_renders(client):
    """Scout-focused tutorial renders and contains scouting UI and navigation."""
    resp = client.get('/setup/tutorial/scout')
    assert resp.status_code == 200
    body = resp.data
    assert b'Scouting Tutorial' in body
    assert b'Show Scouting' in body
    assert b'Start Scouting' in body
    assert b'Practice' in body
    # verify that all tutorial steps exist in the markup
    assert b'id="s-step-2"' in body
    assert b'id="s-step-3"' in body
    assert b'id="s-step-4"' in body
    assert b'id="s-step-5"' in body
    # script should declare the expected number of steps
    assert b'const sSteps = 5' in body
    # preview code should include heading used by the new renderer
    assert b'Scouting Sample' in body
    # pit scouting dropdown should no longer offer swerve-lite
    assert b'Swerve Lite' not in body


def test_analytics_tutorial_renders(client):
    """Analytics-focused tutorial renders and includes chart preview hooks."""
    resp = client.get('/setup/tutorial/analytics')
    assert resp.status_code == 200
    body = resp.data
    assert b'Analytics' in body
    assert b'Show Sample Chart' in body or b'analyticsPreview' in body
    assert b'Configuration' in body



