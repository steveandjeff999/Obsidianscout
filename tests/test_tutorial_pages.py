def test_tutorial_pages(client):
    resp = client.get('/setup/tutorial')
    assert resp.status_code == 200
    body = resp.data
    # Hub should link to split tutorials
    assert b'Scouting Tutorial' in body
    assert b'Analytics Tutorial' in body

    # Scouting tutorial loads
    resp2 = client.get('/setup/tutorial/scouting')
    assert resp2.status_code == 200
    assert b'Scouting Tutorial' in resp2.data
    assert b'Open Scouting Form' in resp2.data

    # Analytics tutorial loads
    resp3 = client.get('/setup/tutorial/analytics')
    assert resp3.status_code == 200
    assert b'Analytics & Configuration' in resp3.data
    assert b'Open Analytics' in resp3.data
