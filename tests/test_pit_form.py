import json
from app import create_app, db
from app.models import User, Team, PitScoutingData


def login_client_via_session(client, user):
    """Utility to bypass login by setting flask-login session keys."""
    with client.session_transaction() as sess:
        # flask-login stores the user id under this key
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_form_prefills_when_team_selected():
    """Selecting a team on the form URL should load any existing pit entry for that scout."""
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        # ensure any leftover user from prior runs is removed to avoid unique constraint failures
        User.query.filter_by(username='pit_tester').delete()
        db.session.commit()
        # create a fresh user and log in via session helper
        u = User(username='pit_tester', scouting_team_number=55555)
        u.set_password('pass')
        db.session.add(u)
        db.session.commit()
        login_client_via_session(client, u)

        # create a team and associated pit data for this user
        team = Team(team_number=7777, team_name='SevenSeven', scouting_team_number=55555)
        db.session.add(team)
        db.session.commit()
        # re-authenticate after commit
        login_client_via_session(client, u)

        # remove any prior pit entries that might use the same local_id
        PitScoutingData.query.filter_by(local_id='test-local').delete()
        db.session.commit()

        pd = PitScoutingData(
            team_id=team.id,
            scout_name=u.username,
            scout_id=u.id,
            scouting_team_number=u.scouting_team_number,
            local_id='test-local',
            data_json=json.dumps({'foo': 'bar'})
        )
        db.session.add(pd)
        db.session.commit()

        # hit the form with ?team=7777 and ensure we see edit heading and team number selected
        # also exercise a debug endpoint to verify pit_data visibility
        @app.route('/__test/debug_pit/<int:teamnum>')
        def __dbg(teamnum):
            t = Team.query.filter_by(team_number=teamnum).first()
            if not t: return 'no team'
            p = PitScoutingData.query.filter_by(team_id=t.id, scout_id=current_user.id).first()
            return f'pit={p}'

        resp_dbg = client.get('/__test/debug_pit/7777')
        # should find our entry
        assert resp_dbg.status_code == 200
        assert b'pit=None' not in resp_dbg.data, "debug endpoint failed to see pit_data"

        resp = client.get('/pit_scouting/form?team=7777')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        assert 'Edit Pit Scouting' in page
        # the dropdown should have the team selected
        assert 'value="7777"' in page
        # the update button should be present
        assert 'Update' in page
        # our recent change adds an explicit opt-out attribute to the team selector
        assert 'data-no-mapped-display' in page
        # and there is also a CSS fallback rule declared for the pit selector id
        assert 'select#team_number + .select-mapped-display' in page

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
        # ensure authenticated
        login_client_via_session(client, u)

        # make sure team 9999 exists but no pit data for this user
        t2 = Team.query.filter_by(team_number=9999).first()
        if not t2:
            t2 = Team(team_number=9999, scouting_team_number=55555)
            db.session.add(t2)
            db.session.commit()

        # ensure still authenticated
        u = User.query.filter_by(username='pit_tester').first()
        if u:
            login_client_via_session(client, u)
        resp3 = client.get('/pit_scouting/form?team=9999&ajax=1')
        assert resp3.status_code == 200
        j3 = resp3.get_json()
        assert j3['success']
        assert j3['pit_data'] == {}


def test_scouting_form_team_selector_optout():
    """scouting form should also flag the team dropdown to skip mapped display"""
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()
        # make sure user exists and log in via session
        u = User.query.filter_by(username='pit_tester').first()
        if u:
            login_client_via_session(client, u)

        resp = client.get('/scouting/form')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        # the team selector should include the opt-out
        assert 'id="team-selector"' in page
        assert 'data-no-mapped-display' in page

        # and the qualitative scouting page also needs the opt‑out on its individual team dropdown
        respq = client.get('/scouting/qualitative')
        assert respq.status_code == 200
        qp = respq.data.decode('utf-8')
        assert 'id="indiv-team-selector"' in qp
        assert 'data-no-mapped-display' in qp
