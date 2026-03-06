def test_updates_page_public_access(client):
    # /updates should be reachable without authentication
    r = client.get('/updates')
    assert r.status_code == 200
    assert b'Latest updates' in r.data
    # When no posts exist, show friendly empty state (and it's public)
    assert b'No updates yet' in r.data or b'No more updates' in r.data


def test_updates_page_handles_memory_error(monkeypatch, client):
    # Simulate list_posts raising a MemoryError; the view should catch it and
    # still return a 200 with a friendly message (not a traceback).
    from app.utils import updates

    def fake_list_posts(limit=None):
        raise MemoryError("simulated oom")

    monkeypatch.setattr(updates, 'list_posts', fake_list_posts)
    r = client.get('/updates')
    assert r.status_code == 200
    # fallback contains the simple inline message or still works gracefully
    assert b'memory' in r.data.lower() or b'updates' in r.data


def test_updates_page_does_not_crash_when_user_proxy_errors(monkeypatch, client):
    # When the underlying `current_user` raises from its properties we should
    # still be able to render a public page thanks to the safe proxy inserted by
    # ``inject_safe_current_user``.
    class BadUser:
        @property
        def is_authenticated(self):
            raise RuntimeError("db is gone")
        def has_role(self, role):
            raise RuntimeError("nope")

    # monkeypatch flask-login's _get_user helper which is what current_user wraps
    import flask_login.utils as utils
    monkeypatch.setattr(utils, '_get_user', lambda: BadUser())

    r = client.get('/updates')
    assert r.status_code == 200
    assert b'Latest updates' in r.data
