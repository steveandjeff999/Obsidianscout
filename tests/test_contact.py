from app import db
from app.models import User


def test_contact_get_and_post(app, client, monkeypatch):
    # Create a test user and login
    with app.app_context():
        u = User(username='contact_user', scouting_team_number=9999, email='test@example.com')
        u.set_password('secret')
        db.session.add(u)
        db.session.commit()

    login_resp = client.post('/auth/login', data={'username': 'contact_user', 'password': 'secret', 'team_number': 9999}, follow_redirects=True)
    assert login_resp.status_code == 200

    # GET contact page
    r = client.get('/contact')
    assert r.status_code == 200
    assert b'obsidianscoutfrc@gmail.com' in r.data
    # Because test instance does not have SMTP configured, show disclaimer
    assert b'will only send messages if the server has email configured' in r.data

    # POST with email send success and reply-to/category
    sent = {}
    def fake_send(to, subj, body, html=None, from_addr=None, bypass_user_opt_out=False, reply_to=None):
        sent['to'] = to
        sent['subject'] = subj
        sent['body'] = body
        sent['reply_to'] = reply_to
        return True, 'Email sent'

    monkeypatch.setattr('app.utils.emailer.send_email', fake_send)
    r2 = client.post('/contact', data={'message': 'Hello team!', 'category': 'Bug', 'reply_to': 'sender@example.com'}, follow_redirects=True)
    assert r2.status_code == 200
    assert b'Message sent' in r2.data
    assert sent.get('reply_to') == 'sender@example.com'
    assert b'[Bug]' in sent.get('subject').encode()

    # POST when email not configured
    monkeypatch.setattr('app.utils.emailer.send_email', lambda *a, **k: (False, 'Email not configured'))
    r3 = client.post('/contact', data={'message': 'Hello again'}, follow_redirects=True)
    assert r3.status_code == 200
    assert b'Server email is not configured' in r3.data
