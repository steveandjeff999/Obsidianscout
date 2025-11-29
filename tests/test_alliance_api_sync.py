import json
from app import create_app
from app.routes.scouting_alliances import perform_periodic_alliance_api_sync


def test_perform_periodic_alliance_api_sync_runs_quietly():
    app = create_app()
    with app.app_context():
        # Run the function to ensure it executes without throwing exceptions
        try:
            perform_periodic_alliance_api_sync()
        except Exception as e:
            # If it raises, fail the test
            raise AssertionError(f"perform_periodic_alliance_api_sync raised an exception: {e}")
