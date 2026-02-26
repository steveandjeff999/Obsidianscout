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
