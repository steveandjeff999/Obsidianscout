"""
Simple smoke test for the mobile graphs visualize endpoint.
Logs in using the Mobile API and requests a visualization PNG.

This script is intended to be run manually during development or CI as a quick sanity check.
"""
import requests
import json
import urllib3
import os

# Configuration - adjust as needed for local/dev runs
BASE_URL = os.environ.get('OBSIDIAN_BASE_URL', 'https://localhost:8080')
API_BASE = f"{BASE_URL}/api/mobile"
# Use admin user which has scouting_team_number = 5454 and has actual data
TEST_USERNAME = os.environ.get('OBSIDIAN_TEST_USERNAME', 'Seth Herod')
TEST_PASSWORD = os.environ.get('OBSIDIAN_TEST_PASSWORD', '5454')
TEST_TEAM_NUMBER = int(os.environ.get('OBSIDIAN_TEST_TEAM', '5454'))

# Disable SSL verification warnings for self-signed certs in dev
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def print_response(name, response):
    print(f"\n{'='*60}")
    print(name)
    print(f"Status: {response.status_code}")
    ctype = response.headers.get('Content-Type', '')
    print(f"Content-Type: {ctype}")
    try:
        if 'application/json' in ctype:
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Binary content length: {len(response.content)} bytes")
    except Exception:
        print("(Unable to decode body)")
    print('='*60 + '\n')


def test_visualize():
    print('Starting visualizer smoke test...')

    # Health check
    h = requests.get(f"{API_BASE}/health", verify=False)
    print_response('Health', h)
    if h.status_code != 200:
        print('Health check failed; aborting test.')
        return

    # Login
    login_payload = {"username": TEST_USERNAME, "password": TEST_PASSWORD, "team_number": TEST_TEAM_NUMBER}
    r = requests.post(f"{API_BASE}/auth/login", json=login_payload, headers={"Content-Type": "application/json"}, verify=False)
    print_response('Login', r)
    if r.status_code != 200 or not r.json().get('success'):
        print('Login failed; aborting test.')
        return

    token = r.json().get('token')
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Request a visualization PNG for the test team
    viz_payload = {
        "vis_type": "team_performance",
        "team_number": TEST_TEAM_NUMBER
    }

    resp = requests.post(f"{API_BASE}/graphs/visualize", json=viz_payload, headers=headers, verify=False)
    print_response('Visualizer', resp)

    # Accept both image/png or a JSON error/fallback
    ctype = resp.headers.get('Content-Type', '')
    if resp.status_code == 200 and (ctype.startswith('image/') or ctype == 'application/octet-stream'):
        print('Visualization produced an image successfully.')
    else:
        print('Visualization did not return an image. Inspect JSON for details.')


if __name__ == '__main__':
    try:
        test_visualize()
    except Exception as e:
        print(f'Error running test: {e}')
        import traceback
        traceback.print_exc()
