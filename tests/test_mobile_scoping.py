import json
from datetime import datetime, timezone
try:
    from app import create_app, db
except Exception:
    create_app = None
    db = None

from app.models import User, Team, Event, Match, ScoutingData
from app.models import ScoutingAlliance, ScoutingAllianceMember, TeamAllianceStatus, ScoutingAllianceEvent


def setup_test_data(app):
    # Create two scouting teams (1111 and 2222) and their related data
    u1 = User(username='team1_user', scouting_team_number=1111)
    u1.set_password('pass')
    db.session.add(u1)

    u2 = User(username='team2_user', scouting_team_number=2222)
    u2.set_password('pass')
    db.session.add(u2)

    # Teams representing scouted teams (team_number is the real team id)
    teamA = Team(team_number=100, team_name='Alpha', scouting_team_number=1111)
    teamB = Team(team_number=200, team_name='Beta', scouting_team_number=2222)
    db.session.add(teamA)
    db.session.add(teamB)

    db.session.flush()

    # Event for teamA only
    evt = Event(name='Event A', code='EVTA', scouting_team_number=1111, year=2024, start_date=datetime(2024, 1, 1, tzinfo=timezone.utc))
    db.session.add(evt)
    db.session.flush()

    # Match for the event, scoped to team 1111 and including team 100
    m = Match(match_number=1, match_type='qual', event_id=evt.id, red_alliance=str(teamA.team_number), blue_alliance='', scouting_team_number=1111)
    db.session.add(m)

    # Scouting data record associated with teamA and the match
    sd = ScoutingData(team_id=teamA.id, match_id=m.id, data={'a': 1}, scout_name=u1.username, scout_id=u1.id, scouting_team_number=1111, timestamp=datetime.now(timezone.utc))
    db.session.add(sd)

    db.session.commit()

    return {'u1': u1, 'u2': u2, 'teamA': teamA, 'teamB': teamB, 'event': evt, 'match': m, 'scouting': sd}


def test_mobile_endpoints_are_scoped_correctly():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()
        # Set up data
        data = setup_test_data(app)
        from app.routes import mobile_api as ma

        token1 = ma.create_token(data['u1'].id, data['u1'].username, data['u1'].scouting_team_number)
        token2 = ma.create_token(data['u2'].id, data['u2'].username, data['u2'].scouting_team_number)

        # 1) /teams?event_id=<event.id> should return teamA for token1
        resp1 = client.get(f"/api/mobile/teams?event_id={data['event'].id}", headers={'Authorization': f'Bearer {token1}'})
        assert resp1.status_code == 200
        j1 = resp1.get_json()
        team_numbers = [t.get('team_number') for t in j1.get('teams', [])]
        assert data['teamA'].team_number in team_numbers

        # token2 should NOT see teamA's teams for that event
        resp2 = client.get(f"/api/mobile/teams?event_id={data['event'].id}", headers={'Authorization': f'Bearer {token2}'})
        assert resp2.status_code == 200
        j2 = resp2.get_json()
        team_numbers2 = [t.get('team_number') for t in j2.get('teams', [])]
        assert data['teamA'].team_number not in team_numbers2

        # 2) /matches?event_id=<event.id> should return match for token1
        r1m = client.get(f"/api/mobile/matches?event_id={data['event'].id}", headers={'Authorization': f'Bearer {token1}'})
        assert r1m.status_code == 200
        jm1 = r1m.get_json()
        assert any(m.get('match_number') == data['match'].match_number for m in jm1.get('matches', []))

        # token2 should not see the matches for team1
        r2m = client.get(f"/api/mobile/matches?event_id={data['event'].id}", headers={'Authorization': f'Bearer {token2}'})
        assert r2m.status_code == 200
        jm2 = r2m.get_json()
        assert not any(m.get('match_number') == data['match'].match_number for m in jm2.get('matches', []))

        # 3) /events should return the event for token1, not for token2
        e1 = client.get('/api/mobile/events', headers={'Authorization': f'Bearer {token1}'})
        assert e1.status_code == 200
        j_e1 = e1.get_json()
        assert any(ev.get('code') == data['event'].code for ev in j_e1.get('events', []))

        e2 = client.get('/api/mobile/events', headers={'Authorization': f'Bearer {token2}'})
        assert e2.status_code == 200
        j_e2 = e2.get_json()
        assert not any(ev.get('code') == data['event'].code for ev in j_e2.get('events', []))

        # 4) /scouting/all should only return entries for the token's scouting_team_number
        s1 = client.get('/api/mobile/scouting/all', headers={'Authorization': f'Bearer {token1}'})
        assert s1.status_code == 200
        js1 = s1.get_json()
        assert any(ent.get('id') == data['scouting'].id for ent in js1.get('entries', []))

        s2 = client.get('/api/mobile/scouting/all', headers={'Authorization': f'Bearer {token2}'})
        assert s2.status_code == 200
        js2 = s2.get_json()
        assert not any(ent.get('id') == data['scouting'].id for ent in js2.get('entries', []))

def test_mobile_history_filters_by_scout_id_and_team():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()
        # Create two users with same username on different teams
        user1 = User(username='duplicate', scouting_team_number=1111)
        user1.set_password('pass')
        db.session.add(user1)

        user2 = User(username='duplicate', scouting_team_number=2222)
        user2.set_password('pass')
        db.session.add(user2)
        db.session.commit()

        team1 = Team(team_number=100, team_name='Alpha', scouting_team_number=1111)
        team2 = Team(team_number=200, team_name='Beta', scouting_team_number=2222)
        db.session.add(team1)
        db.session.add(team2)
        db.session.flush()

        evt = Event(name='Event A', code='EVTA', scouting_team_number=1111, year=2024)
        db.session.add(evt)
        db.session.flush()
        m = Match(match_number=1, match_type='qual', event_id=evt.id, red_alliance=str(team1.team_number), scouting_team_number=1111)
        db.session.add(m)
        db.session.commit()

        # Each user submits a scoring entry for their own scouting team
        sd1 = ScoutingData(team_id=team1.id, match_id=m.id, scout_name='duplicate', scout_id=user1.id, scouting_team_number=1111, data={'a':1})
        db.session.add(sd1)
        # For the other user, create a similar entry but assign to team 2222 (different event ok)
        sd2 = ScoutingData(team_id=team2.id, match_id=m.id, scout_name='duplicate', scout_id=user2.id, scouting_team_number=2222, data={'a':2})
        db.session.add(sd2)
        db.session.commit()

        from app.routes import mobile_api as ma
        token1 = ma.create_token(user1.id, user1.username, user1.scouting_team_number)
        token2 = ma.create_token(user2.id, user2.username, user2.scouting_team_number)

        # mobile history: should return only entries for user's own scout_id
        resp1 = client.get('/api/mobile/scouting/history', headers={'Authorization': f'Bearer {token1}'})
        assert resp1.status_code == 200
        j1 = resp1.get_json()
        ids = [e.get('id') for e in j1.get('entries', [])]
        assert sd1.id in ids
        assert sd2.id not in ids

        resp2 = client.get('/api/mobile/scouting/history', headers={'Authorization': f'Bearer {token2}'})
        j2 = resp2.get_json()
        ids2 = [e.get('id') for e in j2.get('entries', [])]
        assert sd2.id in ids2
        assert sd1.id not in ids2


def test_mobile_alliance_mode_filters_events_teams_matches():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()
        # Create two scouting teams (1111 and 2222) and their related data
        u1 = User(username='team1_user', scouting_team_number=1111)
        u1.set_password('pass')
        db.session.add(u1)

        u2 = User(username='team2_user', scouting_team_number=2222)
        u2.set_password('pass')
        db.session.add(u2)

        teamA = Team(team_number=100, team_name='Alpha', scouting_team_number=1111)
        teamB = Team(team_number=200, team_name='Beta', scouting_team_number=2222)
        db.session.add(teamA)
        db.session.add(teamB)
        db.session.flush()

        # Event A is team-only for 1111
        eventA = Event(name='Event A', code='EVTA', scouting_team_number=1111, year=2024)
        db.session.add(eventA)
        db.session.flush()
        matchA = Match(match_number=1, match_type='qual', event_id=eventA.id, red_alliance=str(teamA.team_number), blue_alliance='', scouting_team_number=1111)
        db.session.add(matchA)

        # Event B is for team 2222 and will be allied
        eventB = Event(name='Event B', code='EVTB', scouting_team_number=2222, year=2024)
        db.session.add(eventB)
        db.session.flush()
        matchB = Match(match_number=2, match_type='qual', event_id=eventB.id, red_alliance=str(teamB.team_number), blue_alliance=str(teamA.team_number), scouting_team_number=2222)
        db.session.add(matchB)

        # Create an alliance joining team numbers 100 and 200
        alliance = ScoutingAlliance(alliance_name='Test Alliance', is_active=True)
        db.session.add(alliance)
        db.session.flush()
        m1 = ScoutingAllianceMember(alliance_id=alliance.id, team_number=100, status='accepted')
        m2 = ScoutingAllianceMember(alliance_id=alliance.id, team_number=200, status='accepted')
        db.session.add(m1)
        db.session.add(m2)
        # Add the alliance event to the alliance
        ae = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='EVTB', event_name='Event B', is_active=True)
        db.session.add(ae)
        # Provide a shared game/pit config for the alliance
        alliance.shared_game_config = json.dumps({'current_event_code': 'EVTB', 'game_name': 'Alliance Config'})
        alliance.shared_pit_config = json.dumps({'pit_field': 'alliance_value'})

        db.session.commit()

        from app.routes import mobile_api as ma
        token1 = ma.create_token(u1.id, u1.username, u1.scouting_team_number)
        token2 = ma.create_token(u2.id, u2.username, u2.scouting_team_number)

        # Initially, no alliance is active for team 1111: team1 should see eventA, not eventB
        resp1 = client.get('/api/mobile/events', headers={'Authorization': f'Bearer {token1}'})
        j1 = resp1.get_json()
        codes1 = [ev.get('code') for ev in j1.get('events', [])]
        assert 'EVTA' in codes1
        assert 'EVTB' not in codes1

        # Now activate the alliance for team 1111
        TeamAllianceStatus.activate_alliance_for_team(1111, alliance.id)

        # Now token1 should see alliance event EVTB and teamB, and not see EVTA
        resp_alliance_events = client.get('/api/mobile/events', headers={'Authorization': f'Bearer {token1}'})
        ja = resp_alliance_events.get_json()
        codes_a = [ev.get('code') for ev in ja.get('events', [])]
        assert 'EVTB' in codes_a
        assert 'EVTA' not in codes_a

        # Teams in alliance should be visible
        rt = client.get('/api/mobile/teams', headers={'Authorization': f'Bearer {token1}'})
        jt = rt.get_json()
        team_nums = [t.get('team_number') for t in jt.get('teams', [])]
        assert 100 in team_nums
        assert 200 in team_nums

        # Matches for EVTB should be visible under alliance mode
        rm = client.get(f"/api/mobile/matches?event_id={eventB.id}", headers={'Authorization': f'Bearer {token1}'})
        jrm = rm.get_json()
        assert any(m.get('match_number') == matchB.match_number for m in jrm.get('matches', []))

        # And for token2 (other member), if not activated, they should not see EVTA
        resp2 = client.get('/api/mobile/events', headers={'Authorization': f'Bearer {token2}'})
        j2 = resp2.get_json()
        codes2 = [ev.get('code') for ev in j2.get('events', [])]
        assert 'EVTA' not in codes2

        # And GET /api/mobile/config/game should expose current_event reflecting alliance
        cfg_resp = client.get('/api/mobile/config/game', headers={'Authorization': f'Bearer {token1}'})
        assert cfg_resp.status_code == 200
        cfg_json = cfg_resp.get_json()
        assert cfg_json.get('current_event') and cfg_json.get('current_event').get('code') == 'EVTB'
        assert cfg_json.get('current_event_is_alliance') is True

        # GET /api/mobile/config/pit raw should reflect alliance pit config
        pit_resp = client.get('/api/mobile/config/pit?raw=true', headers={'Authorization': f'Bearer {token1}'})
        assert pit_resp.status_code == 200
        pit_json = pit_resp.get_json()
        assert pit_json.get('config', {}).get('pit_field') == 'alliance_value'
