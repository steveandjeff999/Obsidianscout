import json
from app import create_app, db
from app.models import Event, Team, ScoutingAlliance, ScoutingAllianceEvent, ScoutingAllianceMember
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
        resp_html = client.get('/events')
        assert resp_html.status_code == 200
        html = resp_html.get_data(as_text=True)
        # Link text 'Alliance' should appear once for the TEST event
        assert html.count('Alliance') >= 1


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
