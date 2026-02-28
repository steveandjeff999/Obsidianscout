from app import db
from app.models import User


def test_qualitative_form_includes_moving_label(app, client):
    # create and log in a user so the form page can be loaded
    with app.app_context():
        u = User(username='qual_user', scouting_team_number=1234, email='q@example.com')
        u.set_password('secret')
        db.session.add(u)
        db.session.commit()

    login_resp = client.post('/auth/login', data={'username': 'qual_user', 'password': 'secret', 'team_number': 1234}, follow_redirects=True)
    assert login_resp.status_code == 200

    # GET qualitative scouting page and look for the updated label text
    r = client.get('/qualitative')
    assert r.status_code == 200
    assert b'Scores while moving' in r.data
    # prediction UI should be present by default
    assert b'Predicted Winner' in r.data

    # create a minimal event, match, and qualitative entry to verify view works
    with app.app_context():
        from app.models import Event, Match, QualitativeScoutingData
        evt = Event(code='TST')
        db.session.add(evt)
        db.session.commit()
        m = Match(match_number=1, match_type='qual', event_id=evt.id,
                  red_alliance='1111', blue_alliance='2222', scouting_team_number=1234)
        db.session.add(m)
        db.session.commit()
        # also test saving prediction through the API when enabled
        resp = client.post('/auth/login', data={'username': 'qual_user', 'password': 'secret', 'team_number': 1234})
        assert resp.status_code == 200
        rv_save = client.post('/qualitative/save', json={
            'qualitative': True,
            'individual_team': True,
            'match_id': m.id,
            'team_number': 1111,
            'team_data': {'individual': {'team_1111': {'ranking': 1}}},
            'show_auto_climb': False,
            'show_endgame_climb': False,
            'match_summary': {'predicted_winner': 'red'}
        })
        assert rv_save.status_code == 200 and rv_save.json.get('success')
        # verify persistence
        entry = QualitativeScoutingData.query.filter_by(scouting_team_number=1234).order_by(QualitativeScoutingData.id.desc()).first()
        assert entry.data.get('_match_summary', {}).get('predicted_winner') == 'red'

        q = QualitativeScoutingData(match_id=m.id,
                                     scouting_team_number=1234,
                                     scout_name='tester',
                                     alliance_scouted='red')
        q.data = {'red': {'team_1111': {'can_score_while_moving': True}}}
        db.session.add(q)
        db.session.commit()
        qid = q.id

    # access view page for the entry
    rv = client.get(f'/qualitative/view/{qid}')
    assert rv.status_code == 200
    assert b'Scores while moving' in rv.data  # ensure display of flag

    # also verify individual team rendering doesn't crash
    with app.app_context():
        from app.models import QualitativeScoutingData
        ind_q = QualitativeScoutingData(match_id=m.id,
                                        scouting_team_number=1234,
                                        scout_name='tester2',
                                        alliance_scouted='team_5678')
        ind_q.data = {'individual': {'team_5678': {'endgame_climb_result': 'success',
                                                   'can_score_while_moving': True}}}
        db.session.add(ind_q)
        db.session.commit()
        ind_id = ind_q.id
    rv2 = client.get(f'/qualitative/view/{ind_id}')
    assert rv2.status_code == 200
    assert b'Scores while moving' in rv2.data
    assert b'Endgame climb' in rv2.data
    assert b'success' in rv2.data.lower()


def test_leaderboard_includes_qualitative_predictions(app, client):
    # set up two users and create qualitative entries with opposing predictions
    with app.app_context():
        from app.models import Event, Match, QualitativeScoutingData, User
        # users
        u1 = User(username='lb1', scouting_team_number=1111)
        u1.set_password('pw1')
        u2 = User(username='lb2', scouting_team_number=2222)
        u2.set_password('pw2')
        db.session.add_all([u1, u2])
        db.session.commit()
        # event & match (red alliance wins)
        evt = Event(code='LBL')
        db.session.add(evt); db.session.commit()
        m2 = Match(match_number=1, match_type='qual', event_id=evt.id,
                   red_alliance='1111', blue_alliance='2222', scouting_team_number=1111)
        db.session.add(m2); db.session.commit()
        mid2 = m2.id
    # user1 logs in and makes correct prediction
    resp1 = client.post('/auth/login', data={'username': 'lb1', 'password': 'pw1', 'team_number': 1111})
    assert resp1.status_code == 200
    payload1 = {
        'qualitative': True,
        'individual_team': True,
        'match_id': mid2,
        'team_number': 1111,
        'team_data': {'individual': {'team_1111': {'ranking': 1}}},
        'show_auto_climb': False,
        'show_endgame_climb': False,
        'match_summary': {'predicted_winner': 'red'}
    }
    client.post('/qualitative/save', json=payload1)
    # log out and login second user
    client.get('/auth/logout')
    resp2 = client.post('/auth/login', data={'username': 'lb2', 'password': 'pw2', 'team_number': 2222})
    assert resp2.status_code == 200
    payload2 = payload1.copy()
    payload2['team_number'] = 2222
    payload2['match_summary'] = {'predicted_winner': 'blue'}
    client.post('/qualitative/save', json=payload2)
    # fetch leaderboard sorted by accuracy
    lb = client.get('/graphs/scout-leaderboard?sort=accuracy')
    assert lb.status_code == 200
    data = lb.data.decode('utf-8')
    # lb1 should appear before lb2 and show 100.0
    assert 'lb1' in data
    assert data.find('lb1') < data.find('lb2')
    assert '100.0' in data

    # also verify predicted winner is shown if stored in match_summary
    with app.app_context():
        from app.models import QualitativeScoutingData
        q2 = QualitativeScoutingData(match_id=m.id,
                                     scouting_team_number=1234,
                                     scout_name='predtest',
                                     alliance_scouted='red')
        q2.data = {'_match_summary': {'predicted_winner': 'blue'}}
        db.session.add(q2)
        db.session.commit()
        q2id = q2.id
    rv3 = client.get(f'/qualitative/view/{q2id}')
    assert rv3.status_code == 200
    assert b'Predicted Winner' in rv3.data
    assert b'BLUE' in rv3.data


def test_prediction_disabled_respected(app, client):
    # if team setting turns off predictions the save endpoint should drop them
    with app.app_context():
        from app.models import Event, Match, User, ScoutingTeamSettings
        # create a user and disable predictions for their team
        u = User(username='preduser', scouting_team_number=5555, email='p@example.com')
        u.set_password('secret')
        db.session.add(u)
        # ensure settings row exists
        ts = ScoutingTeamSettings(scouting_team_number=5555, predictions_enabled=False)
        db.session.add(ts)
        # minimal event/match
        evt = Event(code='PRD')
        db.session.add(evt)
        db.session.commit()
        m = Match(match_number=1, match_type='qual', event_id=evt.id,
                  red_alliance='9999', blue_alliance='8888', scouting_team_number=5555)
        db.session.add(m)
        db.session.commit()
        mid = m.id
    # login
    login_resp = client.post('/auth/login', data={'username': 'preduser', 'password': 'secret', 'team_number': 5555})
    assert login_resp.status_code == 200
    # prepare payload for individual save with a prediction
    payload = {
        'qualitative': True,
        'individual_team': True,
        'match_id': mid,
        'team_number': 9999,
        'team_data': {'individual': {'team_9999': {'ranking': 1}}},
        'show_auto_climb': False,
        'show_endgame_climb': False,
        'match_summary': {'predicted_winner': 'red'}
    }
    rv = client.post('/qualitative/save', json=payload)
    assert rv.status_code == 200 and rv.json.get('success')
    # entry should exist but prediction stripped
    with app.app_context():
        from app.models import QualitativeScoutingData
        entry = QualitativeScoutingData.query.filter_by(scouting_team_number=5555).first()
        assert entry is not None
        ms = entry.data.get('_match_summary', {})
        assert 'predicted_winner' not in ms


def test_alliance_qualitative_view(app, client):
    # create two teams and an alliance, then share a qualitative entry
    with app.app_context():
        from app.models import (
            Team, ScoutingAlliance, ScoutingAllianceMember,
            TeamAllianceStatus, Event, Match, User,
            QualitativeScoutingData, AllianceSharedQualitativeData
        )
        # teams
        t1 = Team(team_number=1111, team_name='Team1111', scouting_team_number=1111)
        t2 = Team(team_number=2222, team_name='Team2222', scouting_team_number=2222)
        db.session.add_all([t1, t2])
        db.session.commit()
        # alliance and members
        alliance = ScoutingAlliance(alliance_name='TestAlliance')
        db.session.add(alliance)
        db.session.flush()
        m1 = ScoutingAllianceMember(alliance_id=alliance.id, team_number=1111,
                                     team_name='Team1111', role='admin', status='accepted')
        m2 = ScoutingAllianceMember(alliance_id=alliance.id, team_number=2222,
                                     team_name='Team2222', role='member', status='accepted')
        db.session.add_all([m1, m2])
        db.session.commit()
        TeamAllianceStatus.activate_alliance_for_team(1111, alliance.id)
        TeamAllianceStatus.activate_alliance_for_team(2222, alliance.id)

        # event and match
        evt = Event(code='ALL')
        db.session.add(evt)
        db.session.commit()
        match = Match(match_number=1, match_type='qual', event_id=evt.id,
                      red_alliance='1111', blue_alliance='2222')
        db.session.add(match)
        db.session.commit()

        # create user and entry for team1
        u1 = User(username='team1', scouting_team_number=1111)
        u1.set_password('pw')
        db.session.add(u1)
        db.session.commit()
        # login via client
        login_resp = client.post('/auth/login', data={'username': 'team1',
                                                       'password': 'pw',
                                                       'team_number': 1111})
        assert login_resp.status_code == 200
        # create qualitative data
        q = QualitativeScoutingData(match_id=match.id,
                                     scouting_team_number=1111,
                                     scout_name='scout1',
                                     alliance_scouted='red')
        q.data = {'red': {'team_1111': {'notes': 'hello'}}}
        db.session.add(q)
        db.session.commit()
        # manually create shared copy (mimic auto_sync)
        shared = AllianceSharedQualitativeData.create_from_qualitative_data(q, alliance.id, 1111)
        db.session.add(shared)
        db.session.commit()
        sid = shared.id
    # logout previous user
    client.get('/auth/logout')

    # login as team2 and attempt to view shared entry
    login_resp2 = client.post('/auth/login', data={'username': 'team2',
                                                    'password': 'pw',
                                                    'team_number': 2222})
    assert login_resp2.status_code == 200

    # first, access using explicit shared_id parameter
    rv_shared = client.get(f'/qualitative/view/{sid}?shared_id={sid}')
    assert rv_shared.status_code == 200
    assert b'hello' in rv_shared.data

    # now access using just the entry id (route should detect alliance entry)
    rv_no_param = client.get(f'/qualitative/view/{sid}')
    assert rv_no_param.status_code == 200
    assert b'hello' in rv_no_param.data

    # and verify QR code pages work the same way; they should not 404
    rv_qr_shared = client.get(f'/qualitative/qr/{sid}?shared_id={sid}')
    assert rv_qr_shared.status_code == 200
    assert b'QR Code' in rv_qr_shared.data

    rv_qr_no_param = client.get(f'/qualitative/qr/{sid}')
    assert rv_qr_no_param.status_code == 200
    assert b'QR Code' in rv_qr_no_param.data
