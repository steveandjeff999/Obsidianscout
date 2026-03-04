import json
from app import create_app, db
from app.models import User, Team, PitScoutingData


def test_form_prefills_when_team_selected():
    """Selecting a team on the form URL should load any existing pit entry for that scout."""
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        # create a user and log in
        u = User(username='pit_tester', scouting_team_number=55555)
        u.set_password('pass')
        db.session.add(u)
        db.session.commit()

        login_resp = client.post(
            '/auth/login',
            data={'username': 'pit_tester', 'password': 'pass', 'team_number': 55555},
            follow_redirects=True
        )
        assert login_resp.status_code in (200, 302)

        # create a team and associated pit data for this user
        team = Team(team_number=7777, team_name='SevenSeven', scouting_team_number=55555)
        db.session.add(team)
        db.session.commit()

        pd = PitScoutingData(
            team_id=team.id,
            scout_name=u.username,
            scout_id=u.id,
            local_id='test-local',
            data_json=json.dumps({'foo': 'bar'})
        )
        db.session.add(pd)
        db.session.commit()

        # hit the form with ?team=7777 and ensure we see edit heading and team number selected
        resp = client.get('/pit_scouting/form?team=7777')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        assert 'Edit Pit Scouting' in page
        # the dropdown should have the team selected
        assert 'value="7777"' in page
        # the update button should be present
        assert 'Update' in page

        # verify ajax endpoint returns the same data
        resp2 = client.get('/pit_scouting/form?team=7777&ajax=1')
        assert resp2.status_code == 200
        jsondata = resp2.get_json()
        assert jsondata['success']
        assert jsondata['pit_data'] == {'foo': 'bar'}

    def test_ajax_endpoint_returns_empty_for_unscouted_team():
        app = create_app(test_config={"TESTING": True})
        with app.app_context():
            client = app.test_client()

            # reuse existing user from previous test or create new
            u = User.query.filter_by(username='pit_tester').first()
            if not u:
                u = User(username='pit_tester', scouting_team_number=55555)
                u.set_password('pass')
                db.session.add(u)
                db.session.commit()
                client.post(
                    '/auth/login',
                    data={'username': 'pit_tester', 'password': 'pass', 'team_number': 55555},
                    follow_redirects=True
                )
            else:
                # login again
                client.post(
                    '/auth/login',
                    data={'username': 'pit_tester', 'password': 'pass', 'team_number': 55555},
                    follow_redirects=True
                )

            # make sure team 9999 exists but no pit data for this user
            t2 = Team.query.filter_by(team_number=9999).first()
            if not t2:
                t2 = Team(team_number=9999, scouting_team_number=55555)
                db.session.add(t2)
                db.session.commit()

            resp3 = client.get('/pit_scouting/form?team=9999&ajax=1')
            assert resp3.status_code == 200
            j3 = resp3.get_json()
            assert j3['success']
            assert j3['pit_data'] == {}
