# Minimal test runner to call dual API functions for event 'okok'
import os
import sys

# Ensure repo root on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app import create_app
from app.utils.api_utils import get_teams_dual_api, get_matches_dual_api


def main():
    # Use test config to avoid touching prod instance files
    test_config = {
        'TESTING': True,
        'SECRET_KEY': 'test',
    }

    app = create_app(test_config=test_config)

    with app.app_context():
        event_code = 'okok'
        print(f"Running dual API test for event: {event_code}\n")

        try:
            teams = get_teams_dual_api(event_code)
            print(f"Teams fetched ({len(teams)}):\n", teams[:5])
        except Exception as e:
            print(f"get_teams_dual_api failed: {e}")

        try:
            matches = get_matches_dual_api(event_code)
            print(f"Matches fetched ({len(matches)}):\n", matches[:5])
        except Exception as e:
            print(f"get_matches_dual_api failed: {e}")


if __name__ == '__main__':
    main()
