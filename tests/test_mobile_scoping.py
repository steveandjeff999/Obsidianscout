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


def test_mobile_can_access_alliance_config_when_not_active():
    """A team that is an accepted alliance member should be able to fetch the
    alliance's shared game/pit config via mobile API even when alliance mode is
    *not* active for that team. Non-members should be forbidden."""
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # Create users and an alliance
        user1 = User(username='member_user', scouting_team_number=1111)
        user1.set_password('pass')
        db.session.add(user1)

        user2 = User(username='other_user', scouting_team_number=2222)
        user2.set_password('pass')
        db.session.add(user2)
        db.session.flush()

        alliance = ScoutingAlliance(alliance_name='Config Access Alliance', is_active=False)
        alliance.shared_game_config = json.dumps({'game_name': 'Alliance Game', 'current_event_code': 'EVX'})
        alliance.shared_pit_config = json.dumps({'pit_field': 'alliance_pit_value'})
        db.session.add(alliance)
        db.session.flush()

        # Add an accepted member whose scouting_team_number is 1111
        m = ScoutingAllianceMember(alliance_id=alliance.id, team_number=1111, status='accepted')
        db.session.add(m)
        db.session.commit()

        from app.routes import mobile_api as ma
        token1 = ma.create_token(user1.id, user1.username, user1.scouting_team_number)
        token2 = ma.create_token(user2.id, user2.username, user2.scouting_team_number)

        # Member should be able to GET alliance game config even though alliance is not active
        resp_g = client.get(f"/api/mobile/alliances/{alliance.id}/config/game", headers={'Authorization': f'Bearer {token1}'})
        assert resp_g.status_code == 200
        jg = resp_g.get_json()
        assert jg.get('success') is True
        assert jg.get('config', {}).get('game_name') == 'Alliance Game'

        # Member should be able to GET alliance pit config
        resp_p = client.get(f"/api/mobile/alliances/{alliance.id}/config/pit", headers={'Authorization': f'Bearer {token1}'})
        assert resp_p.status_code == 200
        jp = resp_p.get_json()
        assert jp.get('success') is True
        assert jp.get('config', {}).get('pit_field') == 'alliance_pit_value'

        # Non-member should be forbidden
        resp_non = client.get(f"/api/mobile/alliances/{alliance.id}/config/game", headers={'Authorization': f'Bearer {token2}'})
        assert resp_non.status_code == 403
        jn = resp_non.get_json()
        assert jn.get('success') is False
        assert 'Forbidden' in jn.get('error', '')

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


def test_mobile_alliance_admin_can_write_config_when_not_active():
    """Alliance admins should be able to update alliance-shared configs via mobile API
    even when their team has not activated alliance mode. Non-admin members are forbidden."""
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # Create a user who will act as alliance admin
        user_admin = User(username='admin_member', scouting_team_number=1111)
        user_admin.set_password('pass')
        db.session.add(user_admin)

        # Non-admin member
        user_member = User(username='normal_member', scouting_team_number=2222)
        user_member.set_password('pass')
        db.session.add(user_member)
        db.session.flush()

        # Create alliance (inactive)
        alliance = ScoutingAlliance(alliance_name='WriteTestAlliance', is_active=False)
        db.session.add(alliance)
        db.session.flush()

        # Add admin member (team 1111) and regular member (team 2222)
        m_admin = ScoutingAllianceMember(alliance_id=alliance.id, team_number=1111, role='admin', status='accepted')
        m_member = ScoutingAllianceMember(alliance_id=alliance.id, team_number=2222, role='member', status='accepted')
        db.session.add(m_admin)
        db.session.add(m_member)
        db.session.commit()

        from app.routes import mobile_api as ma
        token_admin = ma.create_token(user_admin.id, user_admin.username, user_admin.scouting_team_number)
        token_member = ma.create_token(user_member.id, user_member.username, user_member.scouting_team_number)

        # Admin should be able to PUT game config for alliance even when not active
        new_game_cfg = {'game_name': 'Updated Alliance Game', 'current_event_code': 'EVZ'}
        resp_put = client.put(f"/api/mobile/alliances/{alliance.id}/config/game", json=new_game_cfg, headers={'Authorization': f'Bearer {token_admin}'})
        assert resp_put.status_code == 200
        j = resp_put.get_json()
        assert j.get('success') is True

        a = ScoutingAlliance.query.get(alliance.id)
        assert a is not None
        assert json.loads(a.shared_game_config).get('game_name') == 'Updated Alliance Game'

        # Admin should also be able to PUT pit config
        new_pit_cfg = {'pit_field': 'admin_updated'}
        resp_put2 = client.put(f"/api/mobile/alliances/{alliance.id}/config/pit", json=new_pit_cfg, headers={'Authorization': f'Bearer {token_admin}'})
        assert resp_put2.status_code == 200
        j2 = resp_put2.get_json()
        assert j2.get('success') is True
        a2 = ScoutingAlliance.query.get(alliance.id)
        assert json.loads(a2.shared_pit_config).get('pit_field') == 'admin_updated'

        # Non-admin member should be forbidden to update alliance configs
        resp_forbidden = client.put(f"/api/mobile/alliances/{alliance.id}/config/game", json={'game_name': 'bad'}, headers={'Authorization': f'Bearer {token_member}'})
        assert resp_forbidden.status_code == 403
        jf = resp_forbidden.get_json()
        assert jf.get('success') is False

        # Site superadmin should be able to update even if not a member
        # Ensure superadmin role exists
        from app.models import Role
        r_super = Role.query.filter_by(name='superadmin').first()
        if not r_super:
            r_super = Role(name='superadmin')
            db.session.add(r_super)
            db.session.commit()

        super_user = User(username='super_user', scouting_team_number=None)
        super_user.set_password('pass')
        super_user.roles.append(r_super)
        db.session.add(super_user)
        db.session.commit()

        token_super = ma.create_token(super_user.id, super_user.username, super_user.scouting_team_number)
        resp_super = client.put(f"/api/mobile/alliances/{alliance.id}/config/game", json={'game_name': 'super_update'}, headers={'Authorization': f'Bearer {token_super}'})
        assert resp_super.status_code == 200
        jsr = resp_super.get_json()
        assert jsr.get('success') is True


def test_mobile_alliance_endpoints_create_invite_respond_and_toggle():
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        # Create two team users
        u1 = User(username='a_admin', scouting_team_number=1111)
        u1.set_password('pass')
        u1.roles = []
        db.session.add(u1)

        u2 = User(username='b_user', scouting_team_number=2222)
        u2.set_password('pass')
        db.session.add(u2)

        # Give u1 admin role
        r_admin = Role.query.filter_by(name='admin').first()
        if not r_admin:
            r_admin = Role(name='admin')
            db.session.add(r_admin)
            db.session.flush()
        u1.roles.append(r_admin)
        db.session.commit()

        from app.routes import mobile_api as ma
        token1 = ma.create_token(u1.id, u1.username, u1.scouting_team_number)
        token2 = ma.create_token(u2.id, u2.username, u2.scouting_team_number)

        # Create alliance via mobile API
        resp = client.post('/api/mobile/alliances', json={'name': 'Mobile Alliance', 'description': 'desc'}, headers={'Authorization': f'Bearer {token1}'})
        assert resp.status_code == 200
        j = resp.get_json()
        assert j.get('success') is True
        alliance_id = j.get('alliance_id')
        assert alliance_id is not None

        # List alliances for team1 - should include created alliance
        rlist = client.get('/api/mobile/alliances', headers={'Authorization': f'Bearer {token1}'})
        assert rlist.status_code == 200
        jl = rlist.get_json()
        assert any(a.get('id') == alliance_id for a in jl.get('my_alliances', []))

        # Send invitation from team1 to team2
        rinv = client.post(f'/api/mobile/alliances/{alliance_id}/invite', json={'team_number': 2222}, headers={'Authorization': f'Bearer {token1}'})
        assert rinv.status_code == 200
        jr = rinv.get_json()
        assert jr.get('success') is True

        # Team2 should see a pending invitation
        rlist2 = client.get('/api/mobile/alliances', headers={'Authorization': f'Bearer {token2}'})
        assert rlist2.status_code == 200
        jl2 = rlist2.get_json()
        assert any(inv.get('alliance_id') == alliance_id for inv in jl2.get('pending_invitations', []))

        # Respond to invitation (accept)
        # Find the invitation id
        inv_id = jl2.get('pending_invitations')[0].get('id')
        rresp = client.post(f'/api/mobile/invitations/{inv_id}/respond', json={'response': 'accept'}, headers={'Authorization': f'Bearer {token2}'})
        assert rresp.status_code == 200
        jr2 = rresp.get_json()
        assert jr2.get('success') is True

        # Verify member record exists
        m = ScoutingAllianceMember.query.filter_by(alliance_id=alliance_id, team_number=2222).first()
        assert m is not None and m.status == 'accepted'

        # Toggle activation for team2 (activate)
        rtog = client.post(f'/api/mobile/alliances/{alliance_id}/toggle', json={'activate': True}, headers={'Authorization': f'Bearer {token2}'})
        assert rtog.status_code == 200
        jt = rtog.get_json()
        assert jt.get('success') is True

        # Ensure TeamAllianceStatus shows active alliance
        active = TeamAllianceStatus.get_active_alliance_for_team(2222)
        assert active and active.id == alliance_id

        # Prepare some shared data for team2 to exercise copy/remove behavior
        # Create a Team and Match and some scouting/pit data
        team_b = Team(team_number=2222, team_name='Team B')
        db.session.add(team_b)
        ev = Event(name='Test Event', code='TEVT')
        db.session.add(ev)
        db.session.flush()
        match_b = Match(event_id=ev.id, match_number=1)
        db.session.add(match_b)
        db.session.commit()

        sd = ScoutingData(match_id=match_b.id, team_id=team_b.id, scouting_team_number=2222)
        sd.data = {'foo': 'bar'}
        db.session.add(sd)
        pd = PitScoutingData(team_id=team_b.id, event_id=ev.id, scouting_team_number=2222, scout_name='pitter', local_id='local-1')
        pd.data = {'pit': 'info'}
        db.session.add(pd)
        db.session.commit()

        # Create shared copies in the alliance
        shared_sd = AllianceSharedScoutingData.create_from_scouting_data(sd, alliance_id, shared_by_team=2222)
        db.session.add(shared_sd)
        shared_pd = AllianceSharedPitData()
        shared_pd.alliance_id = alliance_id
        shared_pd.original_pit_data_id = pd.id
        shared_pd.source_scouting_team_number = 2222
        shared_pd.team_id = pd.team_id
        shared_pd.event_id = pd.event_id
        shared_pd.scout_name = pd.scout_name
        shared_pd.scout_id = pd.scout_id
        shared_pd.timestamp = pd.timestamp
        shared_pd.data_json = pd.data_json
        shared_pd.shared_by_team = 2222
        db.session.add(shared_pd)
        db.session.commit()

        # Team2 leaves but requests copying data back to their personal tables
        rleave_copy = client.post(f'/api/mobile/alliances/{alliance_id}/leave', headers={'Authorization': f'Bearer {token2}'}, json={'copy_shared_data': True})
        assert rleave_copy.status_code == 200
        jc = rleave_copy.get_json()
        assert jc.get('success') is True

        # Verify team2 member removed
        m2 = ScoutingAllianceMember.query.filter_by(alliance_id=alliance_id, team_number=2222).first()
        assert m2 is None

        # Verify that a scouting data copy exists for the team (count increased)
        copied_sd = ScoutingData.query.filter_by(team_id=team_b.id).all()
        assert len(copied_sd) >= 1

        # Recreate shared entries for team2 and test remove_shared_data behavior
        shared_sd2 = AllianceSharedScoutingData.create_from_scouting_data(sd, alliance_id, shared_by_team=2222)
        db.session.add(shared_sd2)
        shared_pd2 = AllianceSharedPitData()
        shared_pd2.alliance_id = alliance_id
        shared_pd2.original_pit_data_id = pd.id
        shared_pd2.source_scouting_team_number = 2222
        shared_pd2.team_id = pd.team_id
        shared_pd2.event_id = pd.event_id
        shared_pd2.scout_name = pd.scout_name
        shared_pd2.scout_id = pd.scout_id
        shared_pd2.timestamp = pd.timestamp
        shared_pd2.data_json = pd.data_json
        shared_pd2.shared_by_team = 2222
        db.session.add(shared_pd2)
        db.session.commit()

        # Team2 joins again for test (re-add member and make them admin to leave)
        m = ScoutingAllianceMember(alliance_id=alliance_id, team_number=2222, team_name='Team 2222', role='member', status='accepted')
        db.session.add(m)
        db.session.commit()

        # Team2 leaves and requests removal of shared data
        rleave_remove = client.post(f'/api/mobile/alliances/{alliance_id}/leave', headers={'Authorization': f'Bearer {token2}'}, json={'remove_shared_data': True})
        assert rleave_remove.status_code == 200
        jr = rleave_remove.get_json()
        assert jr.get('success') is True

        # Ensure shared data for team2 is removed
        rem_sd = AllianceSharedScoutingData.query.filter_by(alliance_id=alliance_id, source_scouting_team_number=2222).all()
        assert len(rem_sd) == 0

        # Team1 (admin) leaves; since now they are alone, alliance should be deleted
        rleave_admin = client.post(f'/api/mobile/alliances/{alliance_id}/leave', headers={'Authorization': f'Bearer {token1}'})
        assert rleave_admin.status_code == 200
        ja = rleave_admin.get_json()
        assert ja.get('success') is True
        assert ja.get('alliance_deleted') is True

        # Confirm alliance no longer exists
        al = ScoutingAlliance.query.get(alliance_id)
        assert al is None

        # Deactivate
        rdeact = client.post(f'/api/mobile/alliances/{alliance_id}/toggle', json={'activate': False}, headers={'Authorization': f'Bearer {token2}'})
        assert rdeact.status_code == 200
        jd = rdeact.get_json()
        assert jd.get('success') is True

        active2 = TeamAllianceStatus.get_active_alliance_for_team(2222)
        assert not (active2 and active2.is_active)

