import json
try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import User, Role


def _ensure_role(name):
    r = Role.query.filter_by(name=name).first()
    if not r:
        r = Role(name=name, description=f"{name} role")
        db.session.add(r)
        db.session.commit()
    return r


def test_admin_cannot_create_for_other_team():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # Ensure roles exist
        admin_role = _ensure_role('admin')

        # Create an admin user on team 1111
        admin_user = User(username='admin_user', scouting_team_number=1111)
        admin_user.set_password('secret')
        admin_user.roles.append(admin_role)
        db.session.add(admin_user)
        db.session.commit()

        # Login as admin
        login_resp = client.post('/auth/login', data={'username': 'admin_user', 'password': 'secret', 'team_number': 1111}, follow_redirects=True)
        assert login_resp.status_code == 200

        # Attempt to create a user for team 2222 via JSON (no CSRF required for JSON)
        payload = {'username': 'new_user', 'password': 'pw', 'scouting_team_number': 2222}
        resp = client.post('/auth/users', json=payload)
        # Should succeed but create user on admin's team (1111)
        assert resp.status_code in (200, 201)

        u = User.query.filter_by(username='new_user').first()
        assert u is not None
        assert u.scouting_team_number == 1111


def test_superadmin_can_create_for_any_team():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # Ensure roles exist
        super_role = _ensure_role('superadmin')

        # Create a superadmin user
        sa_user = User(username='sa_user', scouting_team_number=None)
        sa_user.set_password('secret')
        sa_user.roles.append(super_role)
        db.session.add(sa_user)
        db.session.commit()

        # Login as superadmin
        login_resp = client.post('/auth/login', data={'username': 'sa_user', 'password': 'secret', 'team_number': ''}, follow_redirects=True)
        assert login_resp.status_code == 200

        # Create a user for team 2222 explicitly
        payload = {'username': 'sa_created_user', 'password': 'pw', 'scouting_team_number': 2222}
        resp = client.post('/auth/users', json=payload)
        assert resp.status_code in (200, 201)

        u = User.query.filter_by(username='sa_created_user').first()
        assert u is not None
        assert u.scouting_team_number == 2222
