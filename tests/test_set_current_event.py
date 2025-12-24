from app import create_app, db
from app.models import Event, ScoutingAlliance, ScoutingAllianceEvent, Team


def test_set_current_event_with_alliance_identifier():
    app = create_app()
    with app.app_context():
        # Create a team and an alliance event
        team = Team(team_number=3333, team_name='Team 3333', scouting_team_number=3333)
        db.session.add(team)
        alliance = ScoutingAlliance(alliance_name='Alliance Test')
        db.session.add(alliance)
        db.session.flush()
        sae = ScoutingAllianceEvent(alliance_id=alliance.id, event_code='OKTU', event_name='Alliance Event OKTU', is_active=True)
        db.session.add(sae)
        db.session.commit()

        client = app.test_client()
        # Call set_current_event with the alliance identifier
        resp = client.get(f"/events/set_current_event/alliance_OKTU")
        assert resp.status_code in (302, 301)
        # Verify game config updated
        from app.utils.config_manager import get_current_game_config
        gc = get_current_game_config()
        assert gc.get('current_event_code') == 'OKTU'


def test_set_current_event_with_numeric_id():
    app = create_app()
    with app.app_context():
        ev = Event(name='Numeric Event', code='NUM', year=2025)
        db.session.add(ev)
        db.session.commit()

        client = app.test_client()
        resp = client.get(f"/events/set_current_event/{ev.id}")
        assert resp.status_code in (302, 301)
        from app.utils.config_manager import get_current_game_config
        gc = get_current_game_config()
        assert gc.get('current_event_code') == 'NUM'