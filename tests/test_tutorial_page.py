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


def test_analytics_tutorial_renders(client):
    """Analytics-focused tutorial renders and includes chart preview hooks."""
    resp = client.get('/setup/tutorial/analytics')
    assert resp.status_code == 200
    body = resp.data
    assert b'Analytics' in body
    assert b'Show Sample Chart' in body or b'analyticsPreview' in body
    assert b'Configuration' in body



