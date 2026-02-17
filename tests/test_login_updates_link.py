def test_login_page_has_whats_new_link(client):
    r = client.get('/auth/login')
    assert r.status_code == 200
    # Link target and visible label
    assert b'href="/updates"' in r.data
    assert b"See what's new" in r.data
