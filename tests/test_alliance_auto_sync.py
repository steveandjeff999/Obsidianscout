import json
from app import create_app, db
from app.models import (
    ScoutingAlliance, ScoutingAllianceMember, TeamAllianceStatus,
    Team, Event, Match, User,
    ScoutingData, PitScoutingData, QualitativeScoutingData,
    AllianceSharedScoutingData, AllianceSharedPitData, AllianceSharedQualitativeData,
    ScoutingAllianceSync
)
from app.routes.scouting import auto_sync_alliance_data, auto_sync_alliance_qualitative_data
from app.routes.pit_scouting import auto_sync_alliance_pit_data
from flask_login import login_user
from datetime import datetime, timezone


def _setup_alliance(app):
    # create two teams and an alliance with both as active members
    team1 = Team(team_number=1111, team_name='Team1111', scouting_team_number=1111)
    team2 = Team(team_number=2222, team_name='Team2222', scouting_team_number=2222)
    db.session.add_all([team1, team2])
    db.session.commit()

    alliance = ScoutingAlliance(alliance_name='TestAlliance')
    db.session.add(alliance)
    db.session.flush()
    member1 = ScoutingAllianceMember(alliance_id=alliance.id, team_number=1111,
                                     team_name='Team 1111', role='admin', status='accepted')
    member2 = ScoutingAllianceMember(alliance_id=alliance.id, team_number=2222,
                                     team_name='Team 2222', role='member', status='accepted')
    db.session.add_all([member1, member2])
    db.session.commit()

    # activate alliance for both teams
    TeamAllianceStatus.activate_alliance_for_team(1111, alliance.id)
    TeamAllianceStatus.activate_alliance_for_team(2222, alliance.id)

    # create an event and a match that both teams can use
    evt = Event(name='EventX', code='EVTX', location='Here', year=2026, scouting_team_number=1111)
    db.session.add(evt)
    db.session.commit()
    # ensure teams are associated (via relationship)
    team1.events.append(evt)
    team2.events.append(evt)
    db.session.commit()

    match = Match(match_number=1, match_type='qualification', event_id=evt.id)
    db.session.add(match)
    db.session.commit()

    return alliance, team1, team2, evt, match


def test_auto_sync_creates_shared_and_records():
    app = create_app()
    with app.app_context():
        # ensure clean database
        db.create_all()

        alliance, team1, team2, evt, match = _setup_alliance(app)

        # create a scouting user for team1 and login
        u1 = User(username='syncuser', scouting_team_number=1111)
        u1.set_password('x')
        db.session.add(u1)
        db.session.commit()
        login_user(u1)

        # create a scouting data entry and attempt auto-sync
        entry = ScoutingData(
            team_id=team1.id,
            match_id=match.id,
            scout_name='tester',
            scout_id=u1.id,
            alliance='red',
            data_json=json.dumps({'foo': 'bar'}),
            scouting_team_number=1111
        )
        db.session.add(entry)
        db.session.commit()

        auto_sync_alliance_data(entry)

        # shared copy should exist
        shared = AllianceSharedScoutingData.query.filter_by(original_scouting_data_id=entry.id).first()
        assert shared is not None
        assert shared.alliance_id == alliance.id

        # there should be a sync record from team1->team2
        sync = ScoutingAllianceSync.query.filter_by(from_team_number=1111, to_team_number=2222).first()
        assert sync is not None
        assert sync.data_type == 'scouting'
        # status should be pending (was created by auto_sync)
        assert sync.sync_status == 'pending'

        # simulate recipient polling via HTTP
        client = app.test_client()
        # login as team2 user
        u2 = User(username='receiver', scouting_team_number=2222)
        u2.set_password('x')
        db.session.add(u2)
        db.session.commit()
        login_user(u2)
        resp = client.get('/alliances/scouting/sync/pending')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'syncs' in data and len(data['syncs']) == 1
        # ack the sync
        sid = data['syncs'][0]['sync_id']
        ack_resp = client.post(f'/alliances/scouting/sync/ack/{sid}')
        assert ack_resp.status_code == 200
        ack_data = ack_resp.get_json()
        assert ack_data.get('success') is True
        # record should now be marked synced
        assert ScoutingAllianceSync.query.get(sid).sync_status == 'synced'


def test_auto_sync_pit_and_qualitative():
    app = create_app()
    with app.app_context():
        db.create_all()
        alliance, team1, team2, evt, match = _setup_alliance(app)

        # login as team1 user
        u1 = User(username='pituser', scouting_team_number=1111)
        u1.set_password('x')
        db.session.add(u1)
        db.session.commit()
        login_user(u1)

        # pit data entry
        pit = PitScoutingData(
            local_id='abc', team_id=team1.id,
            event_id=evt.id,
            scouting_team_number=1111,
            scout_name='pit', scout_id=u1.id,
            data_json=json.dumps({'x': 1}),
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(pit)
        db.session.commit()
        auto_sync_alliance_pit_data(pit)
        shared_pit = AllianceSharedPitData.query.filter_by(original_pit_data_id=pit.id).first()
        assert shared_pit is not None

        # qualitative data entry
        qual = QualitativeScoutingData(
            match_id=match.id,
            scouting_team_number=1111,
            scout_name='qual', scout_id=u1.id,
            alliance_scouted='red',
            data_json=json.dumps({'notes': 'ok'})
        )
        db.session.add(qual)
        db.session.commit()
        auto_sync_alliance_qualitative_data(qual)
        shared_qual = AllianceSharedQualitativeData.query.filter_by(original_qualitative_data_id=qual.id).first()
        assert shared_qual is not None
