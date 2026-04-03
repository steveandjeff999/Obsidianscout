import json
from app import create_app, db
from app.models import User, Team, PitScoutingData, ScoutingAlliance, TeamAllianceStatus


def test_form_prefills_when_team_selected():
    """Selecting a team on the form URL should load any existing pit entry for that scout."""
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        # ensure any leftover user from prior runs is removed to avoid unique constraint failures
        User.query.filter_by(username='pit_tester').delete()
        PitScoutingData.query.filter_by(local_id='test-local').delete()
        db.session.commit()
        # create a fresh user and log in
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
        # our recent change adds an explicit opt-out attribute to the team selector
        assert 'data-no-mapped-display' in page

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


def test_pit_form_uses_alliance_pit_config_in_alliance_mode():
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        # ensure user is clean
        User.query.filter_by(username='alliance_user').delete()
        db.session.commit()

        user = User(username='alliance_user', scouting_team_number=1111)
        user.set_password('pass')
        db.session.add(user)

        alliance = ScoutingAlliance(alliance_name='Alliance Mode Test', is_active=True)
        alliance.shared_game_config = json.dumps({'current_event_code': 'NONE'})
        alliance.shared_pit_config = json.dumps({
            'pit_scouting': {
                'title': 'Alliance Pit Title',
                'description': 'Alliance mode pit form',
                'sections': [
                    {
                        'id': 'secure',
                        'name': 'Secure Section',
                        'elements': [
                            {'id': 'secure_data', 'perm_id': 'secure_data', 'name': 'Secure Data', 'type': 'text'}
                        ]
                    }
                ]
            }
        })
        db.session.add(alliance)
        db.session.commit()

        TeamAllianceStatus.activate_alliance_for_team(1111, alliance.id)

        # Ensure user is treated as logged in without relying on auth workflow
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        resp = client.get('/pit_scouting/form')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        assert 'Alliance Pit Title' in page


def test_pit_form_alliance_gt_image_upload_honors_shared_flag():
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        User.query.filter_by(username='alliance_image_user').delete()
        TeamAllianceStatus.query.filter_by(team_number=3333).delete()
        ScoutingAlliance.query.filter_by(alliance_name='Alliance Image Upload Test').delete()
        db.session.commit()

        user = User(username='alliance_image_user', scouting_team_number=3333)
        user.set_password('pass')
        db.session.add(user)

        alliance = ScoutingAlliance(alliance_name='Alliance Image Upload Test', is_active=True)
        alliance.shared_game_config = json.dumps({'current_event_code': 'NONE'})
        alliance.shared_pit_config = json.dumps({
            'pit_scouting': {
                'title': 'Alliance Image Upload Title',
                'description': 'Alliance mode pit form',
                'image_upload': True,
                'sections': [
                    {
                        'id': 'a',
                        'name': 'A',
                        'elements': [
                            {'id': 'a_field', 'perm_id': 'a_field', 'name': 'A Field', 'type': 'text'}
                        ]
                    }
                ]
            }
        })
        db.session.add(alliance)
        db.session.commit()

        TeamAllianceStatus.activate_alliance_for_team(3333, alliance.id)

        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        resp = client.get('/pit_scouting/form')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        assert 'Alliance Image Upload Title' in page
        assert 'Robot Image' in page


def test_pit_form_uses_team_pit_config_when_alliance_mode_is_inactive():
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        # clean user if exists
        User.query.filter_by(username='team_user').delete()
        db.session.commit()

        user = User(username='team_user', scouting_team_number=2222)
        user.set_password('pass')
        db.session.add(user)

        alliance = ScoutingAlliance(alliance_name='Inactive Alliance', is_active=True)
        alliance.shared_pit_config = json.dumps({
            'pit_scouting': {
                'title': 'Inactive Alliance Pit Title',
                'sections': [
                    {'id': 'a', 'name': 'Alliance Only', 'elements': [
                        {'id': 'a_field', 'perm_id': 'a_field', 'name': 'A', 'type': 'text'}
                    ]}
                ]
            }
        })
        db.session.add(alliance)
        db.session.commit()

        TeamAllianceStatus.activate_alliance_for_team(2222, alliance.id)
        TeamAllianceStatus.deactivate_alliance_for_team(2222)

        # Save explicit team pit config, to ensure current-team config is used
        from app.utils.config_manager import save_pit_config
        team_config = {
            'pit_scouting': {
                'title': 'Team Pit Title',
                'description': 'Team-only mode config',
                'image_upload': True,
                'sections': [
                    {
                        'id': 'team_section',
                        'name': 'Team Section',
                        'elements': [
                            {'id': 'team_field', 'perm_id': 'team_field', 'name': 'Team Field', 'type': 'text'}
                        ]
                    }
                ]
            }
        }
        save_pit_config(team_config, team_number=2222)

        # Ensure user is treated as logged in
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        resp = client.get('/pit_scouting/form')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')

        # Should not show alliance title when alliance mode is inactive
        assert 'Inactive Alliance Pit Title' not in page
        # Should show team title from team config
        assert 'Team Pit Title' in page
        # The merged result should not include default sections that are not in team config
        assert 'Robot Design & Drivetrain' not in page
        # Image upload field should be present when team config enables it
        assert 'Robot Image' in page


def test_scouting_form_team_selector_optout():
    """scouting form should also flag the team dropdown to skip mapped display"""
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()
        resp = client.get('/scouting/form')
        assert resp.status_code == 200
        page = resp.data.decode('utf-8')
        # the team selector should include the opt-out
        assert 'id="team-selector"' in page
        assert 'data-no-mapped-display' in page

        # and the qualitative scouting page also needs the opt‑out on its individual team dropdown
        respq = client.get('/qualitative')
        assert respq.status_code == 200
        qp = respq.data.decode('utf-8')
        assert 'id="indiv-team-selector"' in qp
        assert 'data-no-mapped-display' in qp
