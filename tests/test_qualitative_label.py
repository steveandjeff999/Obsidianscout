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
    # there should be an opt‑out on the individual team dropdown so the JS mapper
    # doesn’t add a redundant team number element
    assert b'id="indiv-team-selector"' in r.data
    assert b'data-no-mapped-display' in r.data
    # prediction UI should be present by default
    assert b'Predicted Winner' in r.data
    # the old per-user toggles should no longer be rendered; visibility is
    # controlled via team settings now
    assert b'id="toggle-auto-climb"' not in r.data
    assert b'id="toggle-endgame-climb"' not in r.data

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


def test_team_view_shows_qualitative(app, client):
    """Ensure the team detail page includes any qualitative notes for that team.

    This test reproduces a regression where `event` was undefined in the
    view route, causing the qualification logic to raise a NameError and the
    page to always show an empty list.  After the fix the note should render.
    """
    with app.app_context():
        from app.models import Team, Event, Match, QualitativeScoutingData

        # create a team and event/match
        t = Team(team_number=9999)
        db.session.add(t)
        evt = Event(code='TV1')
        db.session.add(evt)
        db.session.commit()

        m = Match(match_number=1, match_type='qual', event_id=evt.id,
                  red_alliance='9999', blue_alliance='0000', scouting_team_number=None)
        db.session.add(m)
        db.session.commit()

        # add a qualitative entry that mentions the team
        q = QualitativeScoutingData(match_id=m.id,
                                     scouting_team_number=1234,
                                     scout_name='tester',
                                     alliance_scouted='red')
        q.data = {'red': {'team_9999': {'notes': 'test note'}}}
        db.session.add(q)
        db.session.commit()

    # load the team view page; no event_id parameter should still show the note
    rv = client.get('/teams/9999/view')
    assert rv.status_code == 200
    assert b'test note' in rv.data


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


def test_qualitative_leaderboard_sorting(app, client):
    # verify that query parameters change the ordering of the leaderboard
    with app.app_context():
        from app.models import Event, Match, QualitativeScoutingData, User
        # create user and some basic data
        u = User(username='sortuser', scouting_team_number=3333)
        u.set_password('pw')
        db.session.add(u)
        db.session.commit()
        evt = Event(code='SRT')
        db.session.add(evt); db.session.commit()
        m = Match(match_number=1, match_type='qual', event_id=evt.id,
                  red_alliance='1111', blue_alliance='2222', scouting_team_number=3333)
        db.session.add(m); db.session.commit()
        mid = m.id
        # two qualitative entries with different ratings
        q1 = QualitativeScoutingData(match_id=mid,
                                     scouting_team_number=3333,
                                     scout_name='s1',
                                     alliance_scouted='team_1111')
        q1.data = {'individual': {'team_1111': {'overall_rating': 5}}}
        q2 = QualitativeScoutingData(match_id=mid,
                                     scouting_team_number=3333,
                                     scout_name='s2',
                                     alliance_scouted='team_2222')
        q2.data = {'individual': {'team_2222': {'overall_rating': 1}}}
        db.session.add_all([q1, q2])
        db.session.commit()
    # login as the user
    resp = client.post('/auth/login', data={'username': 'sortuser', 'password': 'pw', 'team_number': 3333})
    assert resp.status_code == 200
    # default (desc by avg rating) should put 1111 before 2222
    r0 = client.get('/scouting/qualitative/leaderboard')
    assert r0.status_code == 200
    s0 = r0.data.decode('utf-8')
    assert s0.find('Team 1111') < s0.find('Team 2222')

    # the sortable columns should be present. there are now two buttons
    # that both sort by average rating (the small progress-bar column and
    # the list of individual ratings), plus the rank column.
    assert b'data-sort="rank"' in r0.data
    # avg_rating should appear at least twice (two headers use it)
    assert r0.data.count(b'data-sort="avg_rating"') >= 2
    assert b'Overall Ratings' in r0.data

    # explicit query parameters are supported for deep-linking as well.
    # ascending rating (low-to-high) reverses the order.
    r1 = client.get('/scouting/qualitative/leaderboard?sort=avg_rating&dir=asc')
    s1 = r1.data.decode('utf-8')
    assert s1.find('Team 2222') < s1.find('Team 1111')

    # sorting by rank is identical to rating but with toggleable direction
    r2 = client.get('/scouting/qualitative/leaderboard?sort=rank&dir=desc')
    s2 = r2.data.decode('utf-8')
    assert s2.find('Team 1111') < s2.find('Team 2222')

    r3 = client.get('/scouting/qualitative/leaderboard?sort=rank&dir=asc')
    s3 = r3.data.decode('utf-8')
    assert s3.find('Team 2222') < s3.find('Team 1111')


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


def test_data_property_unwraps_legacy_structure(app):
    # entries saved with the old mobile API format had an extra "team_data"
    # wrapper; the data property should correct for that so templates don't
    # explode when iterating.
    import json
    with app.app_context():
        from app.models import QualitativeScoutingData
        raw = {
            'team_data': {'red': {'team_1': {'ranking': 1}}},
            '_match_summary': {'predicted_winner': 'blue'}
        }
        q = QualitativeScoutingData(
            match_id=1,
            scouting_team_number=1,
            scout_name='x',
            scout_id=1,
            alliance_scouted='red',
            data_json=json.dumps(raw)
        )
        db.session.add(q)
        db.session.commit()
        fetched = QualitativeScoutingData.query.get(q.id)
        assert fetched.data == {'red': {'team_1': {'ranking': 1}}, '_match_summary': {'predicted_winner': 'blue'}}


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


def test_team_settings_control_qualitative_climb(app, client):
    # team settings should determine whether auto/endgame climb fields are
    # shown and the save API should enforce those rules regardless of what
    # the client submits.
    with app.app_context():
        from app.models import Event, Match, User, ScoutingTeamSettings
        # create a user and explicit settings
        u = User(username='climbuser', scouting_team_number=9999)
        u.set_password('pw')
        db.session.add(u)
        ts = ScoutingTeamSettings(scouting_team_number=9999,
                                   qual_show_auto_climb=True,
                                   qual_show_endgame_climb=False)
        db.session.add(ts)
        # minimal event/match
        evt = Event(code='CLB')
        db.session.add(evt)
        db.session.commit()
        m = Match(match_number=1, match_type='qual', event_id=evt.id,
                  red_alliance='1111', blue_alliance='2222', scouting_team_number=9999)
        db.session.add(m)
        db.session.commit()
        mid = m.id
    # login
    login_resp = client.post('/auth/login', data={'username': 'climbuser', 'password': 'pw', 'team_number': 9999})
    assert login_resp.status_code == 200
    # payload missing any climb results should fail because auto is enabled
    payload = {
        'qualitative': True,
        'individual_team': True,
        'match_id': mid,
        'team_number': 1111,
        'team_data': {'individual': {'team_1111': {'ranking': 1}}},
        'match_summary': {}
    }
    rv = client.post('/qualitative/save', json=payload)
    assert rv.status_code == 400
    assert b'Auto climb required' in rv.data
    # now disable both climb fields and try again - should succeed
    with app.app_context():
        ts2 = ScoutingTeamSettings.query.filter_by(scouting_team_number=9999).first()
        ts2.qual_show_auto_climb = False
        ts2.qual_show_endgame_climb = False
        db.session.commit()
    rv2 = client.post('/qualitative/save', json=payload)
    assert rv2.status_code == 200 and rv2.json.get('success')


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
