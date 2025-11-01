"""
Tinker-style test for mobile group management API.

Usage: run with the dev server running. This script tests the new mobile
endpoints for listing/creating groups and managing group members. It mirrors
the style of other tinker scripts in `tests/` and is intended to be executed
directly (not as a strict pytest test).
"""
import requests
import json
import urllib3
from datetime import datetime

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

    # Create a unique group name to avoid collisions
    grp_name = f"tinker_group_{int(datetime.utcnow().timestamp())}"
    members = [TEST_USERNAME]

    print(f"Creating group '{grp_name}' with members: {members}")
    c = requests.post(f"{BASE_URL}/chat/groups", headers=headers, json={"group": grp_name, "members": members}, verify=False)
    print('Create status:', c.status_code)
    try:
        print(json.dumps(c.json(), indent=2))
    except Exception:
        print('Create response text:', c.text)

    if c.status_code not in (200, 201):
        print('Group creation failed, aborting test')
        return

    # List groups
    print('\nListing groups for team...')
    l = requests.get(f"{BASE_URL}/chat/groups", headers=headers, verify=False)
    print('List status:', l.status_code)
    try:
        j = l.json()
        print(json.dumps(j, indent=2))
    except Exception:
        print('List response text:', l.text)
        return

    groups = j.get('groups') or []
    found = next((g for g in groups if g.get('name') == grp_name), None)
    if not found:
        print('Created group not found in list!')
    else:
        print('Created group found:', found)

    # Get members for the created group
    print(f"\nFetching members for group '{grp_name}'...")
    m = requests.get(f"{BASE_URL}/chat/groups/{grp_name}/members", headers=headers, verify=False)
    print('Members status:', m.status_code)
    try:
        print(json.dumps(m.json(), indent=2))
    except Exception:
        print('Members response text:', m.text)
        return

    # Add a fake member (use a username that likely exists or will be ignored by server scope checks)
    add_member = 'bob'
    print(f"\nAdding member '{add_member}' to group '{grp_name}'...")
    p = requests.post(f"{BASE_URL}/chat/groups/{grp_name}/members", headers=headers, json={"members": [add_member]}, verify=False)
    print('Add status:', p.status_code)
    try:
        print(json.dumps(p.json(), indent=2))
    except Exception:
        print('Add response text:', p.text)

    # Remove the member we just added
    print(f"\nRemoving member '{add_member}' from group '{grp_name}'...")
    d = requests.delete(f"{BASE_URL}/chat/groups/{grp_name}/members", headers=headers, json={"members": [add_member]}, verify=False)
    print('Delete status:', d.status_code)
    try:
        print(json.dumps(d.json(), indent=2))
    except Exception:
        print('Delete response text:', d.text)

    # Send a message to the group
    print(f"\nSending a test message to group '{grp_name}'...")
    send_payload = {"group": grp_name, "body": "Tinker test message to group"}
    s = requests.post(f"{BASE_URL}/chat/send", headers=headers, json=send_payload, verify=False)
    print('Send status:', s.status_code)
    try:
        print(json.dumps(s.json(), indent=2))
    except Exception:
        print('Send response text:', s.text)

    if s.status_code == 201:
        print('Group message sent successfully.')
    else:
        print('Failed to send group message.')


if __name__ == '__main__':
    run()
