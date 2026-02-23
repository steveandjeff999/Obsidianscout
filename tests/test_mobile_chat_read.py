import json
from datetime import datetime, timezone

try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import User


def setup_users(app):
    # create three users on the same scouting team; some usernames include underscores
    alice = User(username='alice', scouting_team_number=1234)
    alice.set_password('pw')
    bob = User(username='bob_smith', scouting_team_number=1234)
    bob.set_password('pw')
    carol = User(username='carol', scouting_team_number=1234)
    carol.set_password('pw')

    db.session.add_all([alice, bob, carol])
    db.session.commit()
    return alice, bob, carol


def login(client, username, team):
    from app.routes import mobile_api as ma
    user = User.query.filter_by(username=username, scouting_team_number=team).first()
    token = ma.create_token(user.id, user.username, team)
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def test_mark_read_does_not_inflate_unread():
    """Regression for bug where marking one convo read caused other chats to show
    unread-count spikes (often due to underscore-containing usernames and the
    old filename-splitting logic).

    We exercise the mobile API end-to-end so that the same helpers run as in
    production.  Without the fix, the unread count after reading the second
    conversation would be too large; after the fix it remains correct.
    """
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        alice, bob, carol = setup_users(app)
        client = app.test_client()

        headers_alice = login(client, alice.username, alice.scouting_team_number)
        headers_bob = login(client, bob.username, bob.scouting_team_number)
        headers_carol = login(client, carol.username, carol.scouting_team_number)

        # bob_smith sends three messages to alice
        r = client.post('/api/mobile/chat/send', headers=headers_bob,
                        json={'conversation_type': 'dm', 'recipient': alice.username, 'message': 'hello1'})
        assert r.status_code == 201
        mid1 = r.get_json()['message']['id']
        r = client.post('/api/mobile/chat/send', headers=headers_bob,
                        json={'conversation_type': 'dm', 'recipient': alice.username, 'message': 'hello2'})
        assert r.status_code == 201
        mid2 = r.get_json()['message']['id']
        r = client.post('/api/mobile/chat/send', headers=headers_bob,
                        json={'conversation_type': 'dm', 'recipient': alice.username, 'message': 'hello3'})
        assert r.status_code == 201

        # carol sends two messages to alice
        r = client.post('/api/mobile/chat/send', headers=headers_carol,
                        json={'conversation_type': 'dm', 'recipient': alice.username, 'message': 'hey1'})
        assert r.status_code == 201
        r = client.post('/api/mobile/chat/send', headers=headers_carol,
                        json={'conversation_type': 'dm', 'recipient': alice.username, 'message': 'hey2'})
        assert r.status_code == 201

        # Alice's state should now reflect five unread messages
        state = client.get('/api/mobile/chat/state', headers=headers_alice).get_json()
        assert state['unreadCount'] == 5

        # Mark conversation with bob_smith as read up through the second message
        r = client.post('/api/mobile/chat/conversations/read', headers=headers_alice,
                        json={'type': 'dm', 'id': bob.username, 'last_read_message_id': mid2})
        assert r.status_code == 200
        state = client.get('/api/mobile/chat/state', headers=headers_alice).get_json()
        # two of bob's messages have been cleared, leaving three unread (1 from bob + 2 from carol)
        assert state['unreadCount'] == 3

        # Now mark the conversation with carol as entirely read
        # fetch one of carol's message ids by grabbing convo history
        hist = client.get(f"/api/mobile/chat/conversations/{carol.username}/messages",
                          headers=headers_alice).get_json()['messages']
        assert len(hist) == 2
        last_carol_id = hist[-1]['id']

        r = client.post('/api/mobile/chat/conversations/read', headers=headers_alice,
                        json={'type': 'dm', 'id': carol.username, 'last_read_message_id': last_carol_id})
        assert r.status_code == 200

        # After reading carol, unread should be reduced to just bob's remaining message
        state = client.get('/api/mobile/chat/state', headers=headers_alice).get_json()
        assert state['unreadCount'] == 1

        # the combined unread notifications endpoint should agree
        unread = client.get('/api/mobile/notifications/unread', headers=headers_alice).get_json()
        assert unread['chat_state']['unreadCount'] == 1


def test_unread_notifications_endpoint_returns_chat_state():
    # simple sanity check that the endpoint returns the chat_state key
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass
        alice, bob, carol = setup_users(app)
        client = app.test_client()
        headers_alice = login(client, alice.username, alice.scouting_team_number)
        r = client.get('/api/mobile/notifications/unread', headers=headers_alice)
        assert r.status_code == 200
        data = r.get_json()
        assert 'chat_state' in data

