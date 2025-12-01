import os
from io import BytesIO
from app import create_app, db
from app.models import User


def test_avatar_static_access_control():
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        # Ensure users table exists
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass

        client = app.test_client()

        # Create two users
        u1 = User(username='u1', scouting_team_number=7777)
        u1.set_password('secret')
        u2 = User(username='u2', scouting_team_number=7777)
        u2.set_password('secret')
        db.session.add(u1)
        db.session.add(u2)
        db.session.commit()

        # Ensure avatar folder exists and create a dummy avatar for u1
        avatar_dir = os.path.join(app.static_folder, 'img', 'avatars')
        os.makedirs(avatar_dir, exist_ok=True)
        avatar_file1 = os.path.join(avatar_dir, f'user_{u1.id}.png')
        with open(avatar_file1, 'wb') as f:
            f.write(b'PNGDATA')

        # Login as u1 (web login via form)
        login_resp = client.post('/auth/login', data={'username': 'u1', 'password': 'secret', 'team_number': 7777}, follow_redirects=True)
        assert login_resp.status_code in (200, 302)

        # Authenticated user u1 should be able to access their avatar
        r_self = client.get(f'/static/img/avatars/user_{u1.id}.png')
        assert r_self.status_code == 200

        # Authenticated user u1 should NOT be able to access u2's avatar
        r_other = client.get(f'/static/img/avatars/user_{u2.id}.png')
        assert r_other.status_code == 403

        # Unauthenticated requests should be rejected (401)
        client.get('/auth/logout', follow_redirects=True)
        r_unauth = client.get(f'/static/img/avatars/user_{u1.id}.png')
        assert r_unauth.status_code == 401

        # Cleanup
        try:
            if os.path.exists(avatar_file1):
                os.remove(avatar_file1)
        except Exception:
            pass
        try:
            User.query.filter(User.id.in_([u1.id, u2.id])).delete(synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
