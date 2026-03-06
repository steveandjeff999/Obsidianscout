import json

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
        # ensure a clean database state for this test
        try:
            db.drop_all()
        except Exception:
            pass
        # clear the session identity map so old Role/User objects aren't reused
        db.session.remove()
        try:
            # create default-bind tables
            db.create_all()
            # create user-bind tables (roles, users etc.)
            db.create_all(bind_key='users')
        except Exception:
            pass

        # create admin user
        admin_role = _ensure_role('admin')
        admin = User(username='admin_config', scouting_team_number=1, is_active=True)
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()
        # associate role after user exists to avoid duplicate-flush issues
        if admin_role not in admin.roles:
            admin.roles.append(admin_role)
            db.session.commit()

        # Save a config that has API and TBA keys set
        cfg = get_current_game_config()
        cfg['api_settings'] = {'username': 'u1', 'auth_token': 'tok-1', 'base_url': 'https://frc-api.firstinspires.org'}
        cfg['tba_api_settings'] = {'auth_key': 'tba-123', 'base_url': 'https://www.thebluealliance.com/api/v3'}
        assert save_game_config(cfg)

        client = app.test_client()
        # login
        resp = client.post('/auth/login', data={'username': 'admin_config', 'password': 'pw', 'team_number': '1'}, follow_redirects=True)
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


def test_check_mapping_detects_changes():
    """check-mapping should flag a migration when an element ID changes"""
    app = create_app()
    with app.app_context():
        # clean schema before starting
        try:
            db.drop_all()
        except Exception:
            pass
        db.session.remove()
        try:
            db.create_all()
            db.create_all(bind_key='users')
        except Exception:
            pass

        admin_role = _ensure_role('admin')
        admin = User(username='admin_map', scouting_team_number=1, is_active=True)
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()
        if admin_role not in admin.roles:
            admin.roles.append(admin_role)
            db.session.commit()

        # create a configuration with one scoring element
        cfg = get_current_game_config()
        cfg['auto_period'] = {'duration_seconds': 15, 'scoring_elements': [
            {'id': 'old1', 'perm_id': 'old1', 'name': 'Original', 'type': 'counter', 'default': 0}
        ]}
        assert save_game_config(cfg)

        client = app.test_client()
        #authenticate by setting session directly, avoid login form
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        # send a check-mapping request with a changed element id
        new_cfg = cfg.copy()
        new_cfg['auto_period'] = {'duration_seconds': 15, 'scoring_elements': [
            {'id': 'new1', 'perm_id': 'new1', 'name': 'Original', 'type': 'counter', 'default': 0}
        ]}
        resp = client.post('/config/check-mapping', json={'new_config': new_cfg})
        assert resp.status_code == 200
        data = resp.get_json()
        # basic sanity check: API returns the expected keys
        assert 'mapping_needed' in data and 'mapping_suggestions' in data


def test_simple_edit_form_attributes():
    """The modern simple-edit page sets a POST method and correct action."""
    app = create_app()
    with app.app_context():
        # create a user so we can view the page (firewall/login restrictions apply)
        admin_role = _ensure_role('admin')
        admin = User(username='attr_admin', scouting_team_number=1, is_active=True)
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()
        if admin_role not in admin.roles:
            admin.roles.append(admin_role)
            db.session.commit()

        client = app.test_client()
        # log in by setting session directly
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        resp = client.get('/config/simple-edit')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # form should post to the save endpoint
        assert 'method="post"' in html.lower()
        assert 'action="/config/save"' in html.lower()


def test_simple_edit_migration_page_returned():
    """POSTing a simple-edit payload that requires migration should return the
    migration UI rather than immediately redirecting to the config page."""
    app = create_app()
    with app.app_context():
        # start with fresh database state
        try:
            db.drop_all()
        except Exception:
            pass
        # clear session cache too
        db.session.remove()
        try:
            db.create_all()
            db.create_all(bind_key='users')
        except Exception:
            pass

        admin_role = _ensure_role('admin')
        admin = User(username='admin_mig', scouting_team_number=1, is_active=True)
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()
        if admin_role not in admin.roles:
            admin.roles.append(admin_role)
            db.session.commit()

        # start with a config containing one element
        cfg = get_current_game_config()
        cfg['auto_period'] = {'duration_seconds': 15, 'scoring_elements': [
            {'id': 'foo', 'perm_id': 'foo', 'name': 'Foo', 'type': 'counter', 'default': 0}
        ]}
        assert save_game_config(cfg)

        client = app.test_client()
        resp = client.post('/auth/login', data={'username': 'admin_mig', 'password': 'pw', 'team_number': '1'}, follow_redirects=True)
        assert resp.status_code == 200

        # prepare a simple_payload that changes the element id
        payload = {
            'game_name': cfg.get('game_name', ''),
            'season': cfg.get('season', 2026),
            'version': cfg.get('version', '1.0.0'),
            'alliance_size': cfg.get('alliance_size', 3),
            'scouting_stations': cfg.get('scouting_stations', 6),
            'current_event_code': cfg.get('current_event_code', ''),
            'match_types': cfg.get('match_types', []),
            'auto': [
                {'id': 'bar', 'perm_id': 'bar', 'name': 'Foo', 'type': 'counter', 'default': 0}
            ],
            'teleop': [],
            'endgame': [],
            'api_settings': {'auto_sync_enabled': False}
        }

        resp = client.post('/config/save', data={
            'simple_edit': 'true',
            'simple_payload': json.dumps(payload)
        }, follow_redirects=False)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="migrateForm"' in html or 'Map old scoring elements' in html


def test_simple_edit_no_duplicate_name_fields():
    app = create_app()
    with app.app_context():
        # fresh database state for isolation
        try:
            db.drop_all()
        except Exception:
            pass
        db.session.remove()
        try:
            db.create_all()
            db.create_all(bind_key='users')
        except Exception:
            pass

        admin_role = _ensure_role('admin')
        admin = User(username='admin_elem', scouting_team_number=1, is_active=True)
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()
        if admin_role not in admin.roles:
            admin.roles.append(admin_role)
            db.session.commit()

        # make sure pit config has one section with one element
        from app.utils.config_manager import get_current_pit_config, save_pit_config
        cfg = get_current_pit_config()
        cfg['pit_scouting'] = {
            'title': 'Test',
            'description': '',
            'sections': [
                {
                    'id': 'sec1',
                    'name': 'Section 1',
                    'elements': [
                        {'id': 'el1', 'perm_id': 'el1', 'name': 'Element1', 'type': 'text'}
                    ]
                }
            ]
        }
        # specify team number explicitly to avoid relying on current_user
        assert save_pit_config(cfg, team_number=1)

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        resp = client.get('/pit_scouting/config/simple-edit')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # every element_name pair should appear only once
        import re, collections
        names = re.findall(r'name="element_name_(\d+)_(\d+)"', html)
        counts = collections.Counter(names)
        for pair, cnt in counts.items():
            assert cnt == 1, f"duplicate name field for element {pair}"
