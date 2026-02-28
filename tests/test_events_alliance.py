import json
from app import create_app, db
from app.models import Event, Team, Match, ScoutingAlliance, ScoutingAllianceEvent, ScoutingAllianceMember
from app.api_models import create_api_key


def test_event_is_alliance_and_deduplicated():
    app = create_app()
    with app.app_context():
        # create a team and event
        team = Team(team_number=9999, team_name='Team 9999', scouting_team_number=9999)
        db.session.add(team)
        db.session.commit()

        # Create two events with same code for the team
        evt1 = Event(name='Test Event 1', code='TEST', location='Loc', year=2025, scouting_team_number=9999)
        evt2 = Event(name='Test Event 2', code='TEST', location='Loc 2', year=2025, scouting_team_number=9999)
        db.session.add(evt1)
        db.session.add(evt2)
        db.session.commit()

        # ensure teams associated to events (via team_event table)
        team.events.append(evt1)
        team.events.append(evt2)
        db.session.commit()

        # Create an alliance with ScoutingAllianceEvent for same code
        alliance = ScoutingAlliance(alliance_name='Test Alliance')
        db.session.add(alliance)
        db.session.flush()
        sa_event = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='TEST', event_name='Test Event 1')
        db.session.add(sa_event)
        member = ScoutingAllianceMember(alliance_id=alliance.id, team_number=9999, team_name='Team 9999', role='admin', status='accepted')
        db.session.add(member)
        db.session.commit()

        # Activate alliance mode for this team so it appears in dropdowns
        from app.models import TeamAllianceStatus
        TeamAllianceStatus.activate_alliance_for_team(9999, alliance.id)

        # Create API key for team
        api_key_info = create_api_key(name='testkey', team_number=9999, created_by='test', permissions={'team_data_access': True})
        api_key = api_key_info['key']

        client = app.test_client()
        resp = client.get('/api/v1/events', headers={'X-API-Key': api_key})
        assert resp.status_code == 200
        data = resp.json
        assert data['success']
        # Only one event returned for code TEST due to dedupe
        events = [e for e in data['events'] if e['code'] == 'TEST']
        assert len(events) == 1
        # Event should be marked as alliance
        assert events[0].get('is_alliance') is True

        # Also check the HTML events page shows a single alliance badge for the deduplicated event
        resp_html = client.get('/events', follow_redirects=True)
        assert resp_html.status_code == 200
        html = resp_html.get_data(as_text=True)
        # Link text 'Alliance' should appear once for the TEST event
        assert html.count('Alliance') >= 1


def test_get_events_with_scouting_data_order_by():
    """Regression test for DISTINCT ON / ORDER BY issue seen in Postgres.
    Previously a query built by get_events_with_scouting_data would add
    ``.distinct(func.upper(Event.code))`` without a matching
    ``ORDER BY`` prefix, causing a ``ProgrammingError`` when callers then
    appended ``.order_by(Event.name)``.  The helper now forces an initial
    order on the same expression.  This test exercises the code path to
    ensure no exception is raised and deduplication still occurs.
    """
    app = create_app()
    with app.app_context():
        # similar setup to earlier tests: create team, events, alliance
        team = Team(team_number=8888, team_name='Team 8888', scouting_team_number=8888)
        db.session.add(team)
        db.session.commit()

        evt1 = Event(name='Alpha Event', code='ALPHA', location='Loc', year=2026, scouting_team_number=8888)
        evt2 = Event(name='Alpha Event Duplicate', code='ALPHA', location='Loc2', year=2026, scouting_team_number=8888)
        db.session.add_all([evt1, evt2])
        db.session.commit()
        team.events.extend([evt1, evt2])
        db.session.commit()

        alliance = ScoutingAlliance(alliance_name='OrderTest')
        # mark alliance as having configs so is_config_complete() returns True and
        # get_alliance_team_numbers() will include our team.
        alliance.game_config_team = 8888
        alliance.pit_config_team = 8888
        db.session.add(alliance)
        db.session.flush()
        sa_event = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='ALPHA', event_name='Alpha Event')
        db.session.add(sa_event)
        member = ScoutingAllianceMember(alliance_id=alliance.id, team_number=8888, team_name='Team 8888', role='admin', status='accepted')
        db.session.add(member)
        db.session.commit()

        # Create a match under one of our events so we have some shared data to copy
        match = Match(match_number=1, match_type='Qualification', event_id=evt1.id, scouting_team_number=8888)
        db.session.add(match)
        db.session.commit()

        # Insert a dummy AllianceSharedScoutingData record for that match
        from app.models import AllianceSharedScoutingData
        share = AllianceSharedScoutingData(
            alliance_id=alliance.id,
            original_scouting_data_id=None,
            source_scouting_team_number=8888,
            match_id=match.id,
            team_id=team.id,
            scout_name='tester',
            scouting_station=1,
            data_json='{}',
            shared_by_team=8888,
            is_active=True
        )
        db.session.add(share)
        db.session.commit()

        from app.models import TeamAllianceStatus
        TeamAllianceStatus.activate_alliance_for_team(8888, alliance.id)

        # Now call the helper that triggered the error previously
        from app.utils.alliance_data import get_events_with_scouting_data
        events, is_alliance, alliance_id = get_events_with_scouting_data()
        # there should be a single event returned for code ALPHA
        assert len([e for e in events if e.code and e.code.upper() == 'ALPHA']) == 1
        assert is_alliance is True
        assert alliance_id == alliance.id


def test_combined_dropdown_events_shows_both_alliance_and_non_alliance():
    app = create_app()
    with app.app_context():
        from app.utils.team_isolation import get_combined_dropdown_events
        # Reuse existing records from previous test setup
        events = get_combined_dropdown_events()
        # Find entries with code 'TEST' (case-insensitive)
        test_events = [e for e in events if getattr(e, 'code', '') and str(e.code).upper() == 'TEST']
        # There should be at least one alliance and one non-alliance entry
        assert any(getattr(e, 'is_alliance', False) for e in test_events)
        assert any(not getattr(e, 'is_alliance', False) for e in test_events)


def test_year_prefixed_event_code_matches_alliance():
    app = create_app()
    with app.app_context():
        # create teams and an alliance
        team_a = Team(team_number=7777, team_name='Team 7777', scouting_team_number=7777)
        team_b = Team(team_number=7778, team_name='Team 7778', scouting_team_number=7778)
        db.session.add_all([team_a, team_b])
        db.session.commit()

        # Create an event owned by an alliance member with a year-prefixed code
        evt = Event(name='Year Prefixed Event', code='2026TEST', location='Loc', year=2026, scouting_team_number=7778)
        db.session.add(evt)
        db.session.commit()

        # Associate event to member team
        team_b.events.append(evt)
        db.session.commit()

        # Create an alliance and add a ScoutingAllianceEvent for 'TEST'
        alliance = ScoutingAlliance(alliance_name='Year Alliance')
        db.session.add(alliance)
        db.session.flush()
        sa_event = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='TEST', event_name='Test Event 1', is_active=True)
        db.session.add(sa_event)
        # Add member entries for both teams and activate alliance for team_a
        member_a = ScoutingAllianceMember(alliance_id=alliance.id, team_number=7777, team_name='Team 7777', role='admin', status='accepted')
        member_b = ScoutingAllianceMember(alliance_id=alliance.id, team_number=7778, team_name='Team 7778', role='member', status='accepted')
        db.session.add_all([member_a, member_b])
        db.session.commit()

        # Activate alliance for team_a so they see shared events
        from app.models import TeamAllianceStatus
        TeamAllianceStatus.activate_alliance_for_team(7777, alliance.id)

        # Now call get_combined_dropdown_events and ensure the year-prefixed event is marked as alliance
        from app.utils.team_isolation import get_combined_dropdown_events
        events = get_combined_dropdown_events()

        # Find the entry for the year-prefixed code
        found = [e for e in events if getattr(e, 'code', '').upper() == '2026TEST']
        assert len(found) == 1
        assert getattr(found[0], 'is_alliance', False) is True




def test_events_page_uses_two_click_delete():
    """Verify /events page uses the inline two-click delete (no modal) for deletable events."""
    app = create_app()
    with app.app_context():
        # create a regular (non-alliance) event
        evt = Event(name='UI Test Event', code='UITEST', location='Loc', year=2026, scouting_team_number=1)
        db.session.add(evt)
        db.session.commit()

        client = app.test_client()
        resp_html = client.get('/events', follow_redirects=True)
        assert resp_html.status_code == 200
        html = resp_html.get_data(as_text=True)

        # Should render the inline delete-confirm form/button
        assert 'delete-confirm-form' in html
        assert 'delete-confirm-btn' in html
        # Should not render the modal for this event id
        assert f'deleteModal{evt.id}' not in html


def test_delete_event_cascades_alliance_selections():
    """Deleting an event should remove any alliance selections owned by that scouting team."""
    app = create_app()
    with app.app_context():
        # ensure clean schema
        try:
            db.create_all()
        except Exception:
            pass

        # create user and login so current_user has a scouting_team_number
        from flask_login import login_user
        u = User(username='deleter', scouting_team_number=1234)
        u.set_password('pass')
        db.session.add(u)
        # create event and an associated alliance selection
        evt = Event(name='Delete Test', code='DEL', year=2026, scouting_team_number=1234)
        db.session.add(evt)
        db.session.commit()

        ally = AllianceSelection(alliance_number=1, event_id=evt.id, scouting_team_number=1234)
        db.session.add(ally)
        db.session.commit()

        assert AllianceSelection.query.filter_by(event_id=evt.id).count() == 1

        client = app.test_client()
        with client:
            # log the user in so scoping works
            login_user(u)
            resp = client.post(f'/events/{evt.id}/delete', follow_redirects=True)
            assert resp.status_code == 200

        # post-delete assertions
        assert Event.query.get(evt.id) is None
        assert AllianceSelection.query.filter_by(event_id=evt.id).count() == 0


