import os
import requests
import urllib3
import time

API_BASE = os.environ.get('MOBILE_API_BASE', 'http://localhost:8080')
LOGIN_URL = f"{API_BASE}/api/mobile/auth/login"
CONFIG_URL = f"{API_BASE}/api/mobile/config/game"

# Disable warnings for self-signed certs in local environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _login(username=None, team_number=None, password='5454'):
    payload = {}
    if username:
        payload['username'] = username
    if team_number is not None:
        payload['team_number'] = team_number
    payload['password'] = password

    resp = requests.post(LOGIN_URL, json=payload, verify=False, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if data.get('success'):
            return data.get('token')
    return None


def test_update_and_restore_game_config():
    """Login as admin, fetch gameconfig, modify it via mobile API, verify, then restore."""
    # Try known admin/superadmin credentials used in other tests
    token = _login(username='Seth Herod', team_number=5454, password='5454')
    if not token:
        # fallback to lowercase username used by some tests
        token = _login(username='seth herod', team_number=5454, password='5454')
    assert token, 'Could not obtain auth token; ensure server is running and credentials are valid.'

    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    # Fetch current config
    resp = requests.get(CONFIG_URL, headers={'Authorization': f'Bearer {token}'}, verify=False, timeout=10)
    assert resp.status_code == 200, f"GET config failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get('success') is True and 'config' in data
    original_config = data['config']

    # Prepare modified config: add a temporary marker
    modified = dict(original_config) if isinstance(original_config, dict) else {}
    marker_key = '__mobile_api_test_marker__'
    marker_value = f"test-{int(time.time())}"
    modified[marker_key] = marker_value

    try:
        # Save via POST
        save_resp = requests.post(CONFIG_URL, headers=headers, json=modified, verify=False, timeout=10)
        assert save_resp.status_code == 200, f"Save failed: {save_resp.status_code} {save_resp.text}"
        save_data = save_resp.json()
        assert save_data.get('success') is True, f"Save response not successful: {save_data}"

        # Fetch again to verify marker
        resp2 = requests.get(CONFIG_URL, headers={'Authorization': f'Bearer {token}'}, verify=False, timeout=10)
        assert resp2.status_code == 200, f"Second GET failed: {resp2.status_code} {resp2.text}"
        data2 = resp2.json()
        cfg2 = data2.get('config')
        assert isinstance(cfg2, dict)
        assert cfg2.get(marker_key) == marker_value, f"Marker not found in saved config: {cfg2.get(marker_key)}"

    finally:
        # Attempt to restore the original config to avoid persisting test artifacts
        try:
            restore_resp = requests.put(CONFIG_URL, headers=headers, json=original_config, verify=False, timeout=10)
            # Best-effort restore; don't fail the test if restore didn't work
            if restore_resp.status_code not in (200, 201):
                print(f"Warning: restore returned {restore_resp.status_code} {restore_resp.text}")
        except Exception as e:
            print(f"Warning: failed to restore config: {e}")
