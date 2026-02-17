import os


def test_superadmin_can_create_post_and_it_appears(app, client, monkeypatch, tmp_path):
    # use temporary instance path so test doesn't touch real instance
    app.instance_path = str(tmp_path)
    os.makedirs(app.instance_path, exist_ok=True)

    # create superadmin user
    with app.app_context():
        from app.models import User, Role, db
        r = Role.query.filter_by(name='superadmin').first()
        if not r:
            r = Role(name='superadmin')
            db.session.add(r)
            db.session.commit()
        u = User(username='sa', scouting_team_number=0, email='sa@example.com')
        u.set_password('pw')
        u.roles.append(r)
        db.session.add(u)
        db.session.commit()

    # login as superadmin
    login = client.post('/auth/login', data={'username': 'sa', 'password': 'pw', 'team_number': 0}, follow_redirects=True)
    assert login.status_code == 200

    # create a post
    resp = client.post('/updates/create', data={'title': 'Integration test post', 'date': '2026-02-17', 'excerpt': 'x', 'body': 'hello **world**', 'published': 'on'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Update post created' in resp.data

    # check instance/updates contains a file
    updates_dir = os.path.join(app.instance_path, 'updates')
    files = os.listdir(updates_dir)
    assert any('integration-test-post' in f or 'Integration test post' in f.lower() or f.endswith('.json') for f in files)

    # public listing shows the post title and admin create button
    r = client.get('/updates')
    assert r.status_code == 200
    assert b'Integration test post' in r.data
    assert b'Create new post' in r.data

    # ensure the Read button links to the created post
    fn = files[0]
    assert f'href="/updates/{fn}"'.encode() in r.data

    # the page should NOT show the old static "3 min read" text
    assert b'3 min read' not in r.data
    # and for our short body we should see an approximate read-time (1 min)
    assert b'1 min read' in r.data

    # view the post
    r2 = client.get(f'/updates/{fn}')
    assert r2.status_code == 200
    assert b'hello' in r2.data
