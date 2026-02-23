"""
Simple tinker-style script to exercise the new combined unread notifications
endpoint (`/api/mobile/notifications/unread`). Run while the dev server is
running and a valid user/team exist (same pattern as other mobile tests).
"""
import requests
import json
import urllib3

BASE_URL = "https://localhost:8080/api/mobile"
TEST_USERNAME = "Seth Herod"
TEST_PASSWORD = "5454"
TEST_TEAM_NUMBER = 5454

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def run():
    print("Requesting token...")
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"username": TEST_USERNAME, "team_number": TEST_TEAM_NUMBER, "password": TEST_PASSWORD},
        verify=False,
    )
    print(f"Login status: {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        print('Login response text:', resp.text)
        return
    if not data.get('success'):
        print('Login failed:', data)
        return
    token = data.get('token')
    headers = {"Authorization": f"Bearer {token}", 'Content-Type': 'application/json'}

    print('\nFetching combined unread notifications...')
    r = requests.get(f"{BASE_URL}/notifications/unread", headers=headers, verify=False)
    print('Status:', r.status_code)
    try:
        print(json.dumps(r.json(), indent=2))
    except Exception:
        print('Response text:', r.text)


if __name__ == '__main__':
    run()
