import json
try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import User, Role
from app.utils.config_manager import save_game_config


def _ensure_role(name):
    r = Role.query.filter_by(name=name).first()
    if not r:
        r = Role(name=name, description=f"{name} role")
        db.session.add(r)
        db.session.commit()
    return r


def test_api_key_banner_shown_for_admin_when_first_key_missing():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # ensure admin role and user
        admin_role = _ensure_role('admin')
        admin_user = User(username='admin_api', scouting_team_number=None)
        admin_user.set_password('secret')
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()

        # Save a global game_config that prefers FIRST but has no auth token
        cfg = {'preferred_api_source': 'first', 'api_settings': {'auth_token': ''}}
        assert save_game_config(cfg)

        # Login as admin and fetch home page
        resp = client.post('/auth/login', data={'username': 'admin_api', 'password': 'secret', 'team_number': ''}, follow_redirects=True)
        assert resp.status_code == 200
        home = client.get('/', follow_redirects=True)
        assert home.status_code == 200
        html = home.get_data(as_text=True)
        assert 'Preferred API source is set to FIRST' in html or 'No API key configured' in html


def test_api_key_banner_not_shown_to_regular_user():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # Create regular user (no admin role)
        user = User(username='normal_user', scouting_team_number=1111)
        user.set_password('secret')
        db.session.add(user)
        db.session.commit()

        # Ensure global config still missing keys
        cfg = {'preferred_api_source': 'first', 'api_settings': {'auth_token': ''}}
        assert save_game_config(cfg)

        # Login as regular user
        resp = client.post('/auth/login', data={'username': 'normal_user', 'password': 'secret', 'team_number': 1111}, follow_redirects=True)
        assert resp.status_code == 200
        home = client.get('/', follow_redirects=True)
        html = home.get_data(as_text=True)
        assert 'Preferred API source is set to FIRST' not in html
