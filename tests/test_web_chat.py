import json

try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import User


def setup_users(team_number=1234):
    """Helper: create two users in the same scouting team and return them."""
    user1 = User(username='user1', scouting_team_number=team_number)
    user1.set_password('secret')
    user2 = User(username='user2', scouting_team_number=team_number)
    user2.set_password('secret')
    db.session.add_all([user1, user2])
    db.session.commit()
    return user1, user2


def login(client, username, team_number):
    return client.post(
        '/auth/login',
        data={'username': username, 'password': 'secret', 'team_number': team_number},
        follow_redirects=True
    )


def test_dm_history_limit_and_pagination():
    """Web chat DM endpoint should honour limit/offset and return sorted history."""
    app = create_app()
    with app.app_context():
        # ensure clean database
        try:
            db.create_all()
        except Exception:
            pass
        # create two test users
        user1, user2 = setup_users(team_number=7777)

        client = app.test_client()
        resp = login(client, 'user1', 7777)
        assert resp.status_code == 200

        # send three messages from user1 to user2
        for i in range(3):
            send_resp = client.post('/chat/dm', json={'recipient': 'user2', 'message': f'hi{i}'})
            assert send_resp.status_code == 200
            body = send_resp.get_json()
            assert body.get('success')

        # fetch full history without paging
        hist_resp = client.get('/chat/dm-history?user=user2')
        assert hist_resp.status_code == 200
        history = hist_resp.get_json().get('history', [])
        assert len(history) == 3
        assert [m['text'] for m in history] == ['hi0', 'hi1', 'hi2']

        # limit to 1 should return only the last message
        hist_l1 = client.get('/chat/dm-history?user=user2&limit=1')
        assert hist_l1.status_code == 200
        h1 = hist_l1.get_json().get('history', [])
        assert len(h1) == 1
        assert h1[0]['text'] == 'hi2'

        # offset support: skip first two messages, fetch one
        hist_off = client.get('/chat/dm-history?user=user2&limit=1&offset=2')
        assert hist_off.status_code == 200
        h2 = hist_off.get_json().get('history', [])
        assert len(h2) == 1
        assert h2[0]['text'] == 'hi2'

        # request history with a user from a different team should return empty list
        outsider = User(username='outsider', scouting_team_number=9999)
        outsider.set_password('secret')
        db.session.add(outsider)
        db.session.commit()
        hist_out = client.get('/chat/dm-history?user=outsider')
        assert hist_out.status_code == 200
        assert hist_out.get_json().get('history', []) == []
