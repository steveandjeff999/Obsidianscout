import os
import requests
import urllib3


API_BASE = os.environ.get('MOBILE_API_BASE', 'http://localhost:8080')
LOGIN_URL = f"{API_BASE}/api/mobile/auth/login"
CONFIG_URL = f"{API_BASE}/api/mobile/config/game"

# Disable warnings for self-signed certs in local environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def test_fetch_gameconfig_by_team_login():
    """Log in using team_number and password, then fetch the full gameconfig.json."""
    # Try login using username + team_number + password first, then fallback
    username_payload = {
        "username": "seth herod",
        "team_number": 5454,
        "password": "5454"
    }

    resp = requests.post(LOGIN_URL, json=username_payload, verify=False, timeout=10)
    if resp.status_code != 200:
        # Fallback to team_number-only login
        payload = {"team_number": 5454, "password": "5454"}
        resp = requests.post(LOGIN_URL, json=payload, verify=False, timeout=10)
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get('success') is True, f"Login not successful: {data}"
    token = data.get('token')
    assert token, "No token returned from login"

    # Fetch config
    headers = {"Authorization": f"Bearer {token}"}
    cfg_resp = requests.get(CONFIG_URL, headers=headers, verify=False, timeout=10)
    assert cfg_resp.status_code == 200, f"Config fetch failed: {cfg_resp.status_code} {cfg_resp.text}"
    cfg_data = cfg_resp.json()
    assert cfg_data.get('success') is True, f"Config response not successful: {cfg_data}"
    assert 'config' in cfg_data, "Config key missing in response"

    config = cfg_data['config']
    # Expect at least a scouting_form or season/game_name keys
    assert isinstance(config, dict), "Config is not a dict"
    assert ('scouting_form' in config) or ('game_name' in config) or ('season' in config), \
        f"Config missing expected keys: {list(config.keys())}"
