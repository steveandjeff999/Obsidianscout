import json
from app import create_app, db
from app.models import User, Event, Match, AllianceSharedScoutingData
from sqlalchemy import text


def test_wipe_database_deletes_alliance_shared_for_event():
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()

        # Create a user and log in
        u = User(username='wipe_user', scouting_team_number=99999)
        u.set_password('secret')
        db.session.add(u)
        db.session.commit()

        login_resp = client.post('/auth/login', data={'username': 'wipe_user', 'password': 'secret', 'team_number': 99999}, follow_redirects=True)
        assert login_resp.status_code in (200, 302)

        # Create an event and a match owned by this user
        evt = Event(name='Wipe Event', code='WIPE', location='Loc', year=2025, scouting_team_number=99999)
        db.session.add(evt)
        db.session.commit()

        m = Match(match_number=1, match_type='quals', event_id=evt.id, red_alliance='99999', blue_alliance='11111', scouting_team_number=99999)
        db.session.add(m)
        db.session.commit()

        # Create an alliance-shared scouting data row referencing this match
        shared = AllianceSharedScoutingData(alliance_id=1, original_scouting_data_id=None, source_scouting_team_number=99999, match_id=m.id, team_id=11111, scout_name='test', scouting_station=1, data_json=json.dumps({'a': 1}), shared_by_team=99999)
        db.session.add(shared)
        db.session.commit()

        # Post to wipe database for the team
        resp = client.post('/data/wipe_database', follow_redirects=True)
        assert resp.status_code in (200, 302)

        # Verify the match and shared data are deleted
        assert Match.query.filter_by(id=m.id).count() == 0
        assert AllianceSharedScoutingData.query.filter_by(id=shared.id).count() == 0


    def test_wipe_database_deletes_team_dependencies():
        from app.models import Team, ScoutingData, PitScoutingData, AllianceSharedPitData, TeamListEntry, AllianceSelection
        app = create_app(test_config={"TESTING": True})
        with app.app_context():
            client = app.test_client()

            # Create a user and log in
            u = User(username='wipe_user2', scouting_team_number=88888)
            u.set_password('secret')
            db.session.add(u)
            db.session.commit()

            login_resp = client.post('/auth/login', data={'username': 'wipe_user2', 'password': 'secret', 'team_number': 88888}, follow_redirects=True)
            assert login_resp.status_code in (200, 302)

            # Create a team owned by this scouting team
            team = Team(team_number=12345, team_name='DeleteMe', scouting_team_number=88888)
            db.session.add(team)
            db.session.commit()

            # Add dependent rows referencing this team
            sd = ScoutingData(match_id=0, team_id=team.id, scouting_team_number=1111, data_json='{}')
            pd = PitScoutingData(team_id=team.id, scout_name='x', local_id='uid', data_json='{}')
            asd = AllianceSharedScoutingData(alliance_id=1, original_scouting_data_id=None, source_scouting_team_number=1111, match_id=0, team_id=team.id, scout_name='x', scouting_station=1, data_json='{}', shared_by_team=1111)
            apd = AllianceSharedPitData(alliance_id=1, original_pit_data_id=None, source_scouting_team_number=1111, team_id=team.id, scout_name='x', data_json='{}', shared_by_team=1111)
            tle = TeamListEntry(team_id=team.id, event_id=1, reason='r')
            alliance = AllianceSelection(alliance_number=1, captain=team.id, event_id=1)

            db.session.add_all([sd, pd, asd, apd, tle, alliance])
            db.session.commit()

            # Post to wipe database for the team
            resp = client.post('/data/wipe_database', follow_redirects=True)
            assert resp.status_code in (200, 302)

            # Verify all dependent rows referencing the team were removed and the team is deleted
            assert Team.query.filter_by(id=team.id).count() == 0
            assert ScoutingData.query.filter_by(team_id=team.id).count() == 0
            assert PitScoutingData.query.filter_by(team_id=team.id).count() == 0
            assert AllianceSharedScoutingData.query.filter_by(team_id=team.id).count() == 0
            assert AllianceSharedPitData.query.filter_by(team_id=team.id).count() == 0
            assert TeamListEntry.query.filter_by(team_id=team.id).count() == 0
            assert AllianceSelection.query.filter_by(id=alliance.id).first().captain is None


def test_wipe_database_with_foreign_key_constraints():
    """Test that wipe_database handles foreign key constraints automatically"""
    from app.models import Team, Event, Match, TeamListEntry, AllianceSelection, team_event
    
    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        client = app.test_client()
        
        # Enable foreign key constraints for this test
        db.session.execute(text('PRAGMA foreign_keys = ON'))
        db.session.commit()
        
        # Create a user and log in
        u = User(username='fk_test_user', scouting_team_number=77777)
        u.set_password('secret')
        db.session.add(u)
        db.session.commit()

        login_resp = client.post('/auth/login', data={'username': 'fk_test_user', 'password': 'secret', 'team_number': 77777}, follow_redirects=True)
        assert login_resp.status_code in (200, 302)
        
        # Create an event
        evt = Event(name='FK Test Event', code='FKTEST', location='TestLoc', year=2025, scouting_team_number=77777)
        db.session.add(evt)
        db.session.commit()
        
        # Create a team
        team = Team(team_number=7777, team_name='Test Team', scouting_team_number=77777)
        db.session.add(team)
        db.session.commit()
        
        # Create team-event association (this creates a foreign key dependency)
        team.events.append(evt)
        db.session.commit()
        
        # Create a match for the event (foreign key to event)
        match = Match(
            match_number=1, 
            match_type='quals', 
            event_id=evt.id, 
            red_alliance=str(team.team_number), 
            blue_alliance='9999',
            scouting_team_number=77777
        )
        db.session.add(match)
        db.session.commit()
        
        # Create alliance selection (foreign key to event and team)
        alliance = AllianceSelection(
            alliance_number=1,
            captain=team.id,
            event_id=evt.id,
            scouting_team_number=77777
        )
        db.session.add(alliance)
        db.session.commit()
        
        # Create team list entry (foreign key to team and event)
        tle = TeamListEntry(
            team_id=team.id,
            event_id=evt.id,
            reason='Test',
            scouting_team_number=77777
        )
        db.session.add(tle)
        db.session.commit()
        
        # Verify data exists
        assert Event.query.filter_by(id=evt.id).count() == 1
        assert Team.query.filter_by(id=team.id).count() == 1
        assert Match.query.filter_by(id=match.id).count() == 1
        assert AllianceSelection.query.filter_by(id=alliance.id).count() == 1
        assert TeamListEntry.query.filter_by(id=tle.id).count() == 1
        
        # Now try to wipe the database - this should succeed even with FK constraints
        # The auto-fix should handle any constraint issues automatically
        resp = client.post('/data/wipe_database', follow_redirects=True)
        assert resp.status_code in (200, 302)
        
        # Verify all data was deleted successfully
        assert Event.query.filter_by(scouting_team_number=77777).count() == 0
        assert Team.query.filter_by(scouting_team_number=77777).count() == 0
        assert Match.query.filter_by(scouting_team_number=77777).count() == 0
        assert AllianceSelection.query.filter_by(scouting_team_number=77777).count() == 0
        assert TeamListEntry.query.filter_by(scouting_team_number=77777).count() == 0
        
        # Check that the response indicates success
        assert resp.status_code == 200 or b'success' in resp.data.lower()


if __name__ == '__main__':
    # Run the new test
    test_wipe_database_with_foreign_key_constraints()
    print("✅ Foreign key constraint test passed!")
