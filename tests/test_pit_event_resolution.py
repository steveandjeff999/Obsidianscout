import json
from app import create_app, db
from app.models import Team, Event, ScoutingAlliance, ScoutingAllianceEvent, TeamAllianceStatus


def test_get_event_by_code_prefers_local_when_no_active_alliance():
    app = create_app()
    with app.app_context():
        # Create a team and a local event
        team = Team(team_number=1111, team_name='Team 1111', scouting_team_number=1111)
        db.session.add(team)
        ev = Event(name='Local Event', code='OKOK', year=2025, scouting_team_number=1111)
        db.session.add(ev)
        db.session.commit()

        # Create an alliance event record (but do NOT activate alliance mode for this team)
        alliance = ScoutingAlliance(alliance_name='Test Alliance')
        db.session.add(alliance)
        db.session.flush()
        sae = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='OKOK', event_name='Alliance Event', is_active=True)
        db.session.add(sae)
        db.session.commit()

        # Call get_event_by_code with request context and g.scouting_team_number set
        from flask import g
        from app.utils.team_isolation import get_event_by_code

        with app.test_request_context():
            g.scouting_team_number = 1111
            result = get_event_by_code('OKOK')
            # Should return the local Event object, not a synthetic alliance object
            assert not getattr(result, 'is_alliance', False)
            assert isinstance(result.id, int)


def test_get_event_by_code_returns_alliance_object_when_alliance_mode_active():
    app = create_app()
    with app.app_context():
        # Reuse or create records
        team = Team(team_number=2222, team_name='Team 2222', scouting_team_number=2222)
        db.session.add(team)
        db.session.commit()

        alliance = ScoutingAlliance(alliance_name='Active Alliance')
        db.session.add(alliance)
        db.session.flush()
        sae = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='ALLA', event_name='Alliance Only Event', is_active=True)
        db.session.add(sae)
        # Activate alliance mode for the team
        status = TeamAllianceStatus(team_number=2222, active_alliance_id=alliance.id, is_alliance_mode_active=True)
        db.session.add(status)
        db.session.commit()

        from flask import g
        from app.utils.team_isolation import get_event_by_code

        with app.test_request_context():
            g.scouting_team_number = 2222
            result = get_event_by_code('ALLA')
            # Now it should return a synthetic alliance-like object
            assert getattr(result, 'is_alliance', False)
            assert isinstance(result.id, str) and str(result.id).startswith('alliance_')
