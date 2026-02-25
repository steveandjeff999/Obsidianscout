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
