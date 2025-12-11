from app import create_app, db
from app.models import Team, Event, Match
from app.utils.analysis import calculate_team_metrics


def test_starting_points_applies_to_calculations():
    app = create_app()
    with app.app_context():
        # Ensure fresh testing DB state
        db.drop_all()
        db.create_all()

        # Create team and event
        team = Team(team_number=9999, team_name='Test Team')
        event = Event(name='Test Event', code='TEV', year=2025)
        db.session.add(team)
        db.session.add(event)
        db.session.commit()

        # Set per-team starting points settings
        team.starting_points = 42.5
        team.starting_points_threshold = 2
        team.starting_points_enabled = True
        db.session.add(team)
        db.session.commit()

        # No ScoutingData exists -> calculate_team_metrics should use starting_points
        result = calculate_team_metrics(team.id, event_id=event.id)
        assert result is not None
        metrics = result.get('metrics', {})
        # Ensure we have a total_points metric and it matches the starting points
        assert 'total_points' in metrics
        assert abs(metrics['total_points'] - 42.5) < 0.001
