import os
import requests
import urllib3
import time

API_BASE = os.environ.get('MOBILE_API_BASE', 'http://localhost:8080')
REGISTER_URL = f"{API_BASE}/api/mobile/auth/register"

# Disable warnings for self-signed certs in local environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def test_register_new_user():
    """Attempt to register a new user using the mobile register endpoint.

    This test requires a running server. It will try to create a moderately
    unique username using the current timestamp so repeated runs are unlikely
    to collide.
    """
    suffix = int(time.time()) % 100000
    username = f"mobile_test_{suffix}"
    payload = {
        'username': username,
        'password': 'test-pass-1234',
        'confirm_password': 'test-pass-1234',
        'team_number': 5454,
        'email': None
    }

    resp = requests.post(REGISTER_URL, json=payload, verify=False, timeout=10)

    # Accept created or conflict if a test run produced the same username
    assert resp.status_code in (201, 409), f"Unexpected status: {resp.status_code} {resp.text}"
    if resp.status_code == 201:
        data = resp.json()
        assert data.get('success') is True
        assert 'token' in data
        assert 'user' in data and data['user'].get('username') == username
