import json
from datetime import datetime, timezone, timedelta
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
        # clean database to avoid leftovers from other tests
        try:
            db.drop_all()
        except Exception:
            pass
        # clear the session so stale objects don't stick around
        db.session.remove()
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # Ensure roles exist and re-query to avoid stale session state
        _ensure_role('admin')
        admin_role = Role.query.filter_by(name='admin').first()

        # Create an admin user on team 1111 (assign role manually)
        admin_user = User(username='admin_user', scouting_team_number=1111)
        admin_user.set_password('secret')
        db.session.add(admin_user)
        db.session.commit()
        # manually link role to avoid relationship-flush bugs
        from app.models import user_roles
        db.session.execute(
            user_roles.insert().values(user_id=admin_user.id, role_id=admin_role.id)
        )
        db.session.commit()

        # Login as admin
        login_resp = client.post('/auth/login', data={'username': 'admin_user', 'password': 'secret', 'team_number': 1111}, follow_redirects=True)
        assert login_resp.status_code == 200
        # sanity check: superadmin page should be reachable
        check = client.get('/auth/users')
        assert check.status_code == 200

        # Attempt to create a user for team 2222 via JSON (no CSRF required for JSON)
        payload = {'username': 'new_user', 'password': 'pw', 'scouting_team_number': 2222}
        resp = client.post('/auth/users', json=payload)
        # API may redirect on HTML path (302) or return JSON success codes
        assert resp.status_code in (200, 201, 302)
        # ensure creation occurred regardless of response type
        u = User.query.filter_by(username='new_user').first()
        assert u is not None and u.scouting_team_number == 1111

        u = User.query.filter_by(username='new_user').first()
        assert u is not None
        assert u.scouting_team_number == 1111


def test_superadmin_can_create_for_any_team():
    app = create_app()
    with app.app_context():
        # clean slate each run
        try:
            db.drop_all()
        except Exception:
            pass
        db.session.remove()
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # Ensure roles exist and reload from DB
        _ensure_role('superadmin')
        super_role = Role.query.filter_by(name='superadmin').first()

        # Create a superadmin user (roles added afterwards)
        sa_user = User(username='sa_user', scouting_team_number=None)
        sa_user.set_password('secret')
        db.session.add(sa_user)
        db.session.commit()
        from app.models import user_roles
        db.session.execute(
            user_roles.insert().values(user_id=sa_user.id, role_id=super_role.id)
        )
        db.session.commit()

        # Login as superadmin
        login_resp = client.post('/auth/login', data={'username': 'sa_user', 'password': 'secret', 'team_number': ''}, follow_redirects=True)
        assert login_resp.status_code == 200
        check = client.get('/auth/users')
        assert check.status_code == 200

        # Create a user for team 2222 explicitly
        payload = {'username': 'sa_created_user', 'password': 'pw', 'scouting_team_number': 2222}
        resp = client.post('/auth/users', json=payload)
        assert resp.status_code in (200, 201, 302)
        # verify user creation
        u = User.query.filter_by(username='sa_created_user').first()
        assert u is not None
        assert u.scouting_team_number == 2222


def test_superadmin_pagination_and_sorting():
    """Superadmins should be able to page through all users and sort globally.

    This test creates more users than a single page, then verifies that the
    second page contains users not present on the first page.  It also checks
    that sorting by last_used returns results in the correct order.
    """
    app = create_app()
    with app.app_context():
        try:
            db.drop_all()
        except Exception:
            pass
        db.session.remove()
        try:
            db.create_all()
        except Exception:
            pass
        client = app.test_client()

        # Ensure roles exist and reload
        _ensure_role('superadmin')
        super_role = Role.query.filter_by(name='superadmin').first()

        # Create a superadmin user (assign role after initial commit)
        sa_user = User(username='sa_user2', scouting_team_number=None)
        sa_user.set_password('secret')
        db.session.add(sa_user)
        db.session.commit()
        from app.models import user_roles
        db.session.execute(
            user_roles.insert().values(user_id=sa_user.id, role_id=super_role.id)
        )
        db.session.commit()

        # generate 60 additional users with distinct last_used timestamps
        base = datetime.now(timezone.utc)
        for i in range(60):
            u = User(username=f'paged{i:02d}', scouting_team_number=i)
            u.set_password('pw')
            # stagger last_used so we can sort
            u.last_used = base.replace(microsecond=0) + timedelta(seconds=i)
            db.session.add(u)
        db.session.commit()

        # login as superadmin
        login_resp = client.post('/auth/login', data={'username': 'sa_user2', 'password': 'secret', 'team_number': ''}, follow_redirects=True)
        assert login_resp.status_code == 200

        # request first page
        resp1 = client.get('/auth/users?page=1')
        assert resp1.status_code == 200
        html1 = resp1.get_data(as_text=True)
        # first page should include paged00 but not paged50 (since per_page default 50)
        assert 'paged00' in html1
        assert 'paged50' not in html1

        # request second page
        resp2 = client.get('/auth/users?page=2')
        assert resp2.status_code == 200
        html2 = resp2.get_data(as_text=True)
        assert 'paged50' in html2
        assert 'paged00' not in html2

        # check sorting by last_used descending: the first username should be the
        # one with largest timestamp (paged59)
        resp_sort = client.get('/auth/users?sort=last_used&order=desc&page=1')
        assert resp_sort.status_code == 200
        htmls = resp_sort.get_data(as_text=True)
        # ensure the first occurrence of a paged user is paged59
        idx59 = htmls.find('paged59')
        idxother = htmls.find('paged58')
        assert idx59 != -1 and idx59 < idxother
