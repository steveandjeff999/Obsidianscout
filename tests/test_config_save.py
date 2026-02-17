from app import create_app, db
from app.models import User, Role
from app.utils.config_manager import save_game_config, get_current_game_config


def _ensure_role(name):
    r = Role.query.filter_by(name=name).first()
    if not r:
        r = Role(name=name, description=f"{name} role")
        db.session.add(r)
        db.session.commit()
    return r


def test_simple_edit_allows_clearing_api_and_tba_keys():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        # create admin user
        admin_role = _ensure_role('admin')
        admin = User(username='admin_config', scouting_team_number=None)
        admin.set_password('pw')
        admin.roles.append(admin_role)
        db.session.add(admin)
        db.session.commit()

        # Save a config that has API and TBA keys set
        cfg = get_current_game_config()
        cfg['api_settings'] = {'username': 'u1', 'auth_token': 'tok-1', 'base_url': 'https://frc-api.firstinspires.org'}
        cfg['tba_api_settings'] = {'auth_key': 'tba-123', 'base_url': 'https://www.thebluealliance.com/api/v3'}
        assert save_game_config(cfg)

        client = app.test_client()
        # login
        resp = client.post('/auth/login', data={'username': 'admin_config', 'password': 'pw', 'team_number': ''}, follow_redirects=True)
        assert resp.status_code == 200

        # Submit simple-edit save with blank API/TBA fields (user intentionally clears them)
        resp = client.post('/config/save', data={
            'simple_edit': 'true',
            'api_username': '',
            'api_auth_token': '',
            'tba_auth_key': '',
            'skip_migration': 'true'
        }, follow_redirects=True)
        assert resp.status_code in (200, 302)

        new_cfg = get_current_game_config()
        assert new_cfg.get('api_settings', {}).get('username', None) == ''
        assert new_cfg.get('api_settings', {}).get('auth_token', None) == ''
        assert new_cfg.get('tba_api_settings', {}).get('auth_key', None) == ''
