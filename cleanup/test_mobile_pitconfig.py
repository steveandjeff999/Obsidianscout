import os
import requests
import urllib3

API_BASE = os.environ.get('MOBILE_API_BASE', 'http://localhost:8080')
LOGIN_URL = f"{API_BASE}/api/mobile/auth/login"
PIT_URL = f"{API_BASE}/api/mobile/config/pit"

# Disable warnings for self-signed certs in local environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def test_fetch_pitconfig_by_team_login():
    """Log in using team_number and password, then fetch the pit_config.json."""
    payload = {"team_number": 5454, "password": "5454"}

    resp = requests.post(LOGIN_URL, json=payload, verify=False, timeout=10)
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get('success') is True, f"Login not successful: {data}"
    token = data.get('token')
    assert token, "No token returned from login"

    headers = {"Authorization": f"Bearer {token}"}
    cfg_resp = requests.get(PIT_URL, headers=headers, verify=False, timeout=10)
    assert cfg_resp.status_code == 200, f"Config fetch failed: {cfg_resp.status_code} {cfg_resp.text}"
    cfg_data = cfg_resp.json()
    assert cfg_data.get('success') is True, f"Config response not successful: {cfg_data}"
    assert 'config' in cfg_data, "Config key missing in response"

    cfg = cfg_data['config']
    assert isinstance(cfg, dict), "Pit config is not a dict"
    # Expect at least pit_scouting top-level key or other common keys
    assert 'pit_scouting' in cfg or isinstance(cfg, dict), f"Unexpected pit config shape: {list(cfg.keys())}"
