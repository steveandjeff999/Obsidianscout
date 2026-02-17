def test_updates_page_public_access(client):
    # /updates should be reachable without authentication
    r = client.get('/updates')
    assert r.status_code == 200
    assert b'Latest updates' in r.data
    # When no posts exist, show friendly empty state (and it's public)
    assert b'No updates yet' in r.data or b'No more updates' in r.data
