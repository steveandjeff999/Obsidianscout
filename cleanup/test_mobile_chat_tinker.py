"""
Mobile Chat Tinker test script

This script is written in the same style as `test_mobile_api.py`. It logs in using
mobile API credentials, reads the mobile chat state, sends a DM (mobile API), and
then reads the chat state again to demonstrate the unread counter increment.

It is intended for manual / local testing (not as a unit test). Run it while the
server is running locally.

Usage:
    python test_mobile_chat_tinker.py

"""
import requests
import json
import uuid
from datetime import datetime

# Configuration - adapt as needed for your local server
BASE_URL = "https://localhost:8080/api/mobile"
TEST_USERNAME = "Seth Herod"  # existing user on your instance
TEST_PASSWORD = "5454"
TEST_TEAM_NUMBER = 5454

# Disable SSL verification warnings for self-signed certs
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def print_response(name, response):
    print(f"\n{'='*60}")
    print(name)
    print(f"{'='*60}")
    print(f"Status Code: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except Exception:
        print(response.text)
    print(f"{'='*60}\n")


def main():
    print("Mobile Chat Tinker Test")
    print(f"Base URL: {BASE_URL}")

    # 1) Login via mobile API
    login_payload = {"username": TEST_USERNAME, "password": TEST_PASSWORD, "team_number": TEST_TEAM_NUMBER}
    r = requests.post(f"{BASE_URL}/auth/login", json=login_payload, verify=False)
    print_response('Login', r)
    if r.status_code != 200:
        print("Login failed — make sure server is running and credentials are correct.")
        return

    token = r.json().get('token')
    user = r.json().get('user') or {}
    user_id = user.get('id')

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 2) Read initial chat state
    r = requests.get(f"{BASE_URL}/chat/state", headers=headers, verify=False)
    print_response('Initial chat state', r)
    initial_unread = 0
    if r.status_code == 200:
        try:
            initial_unread = int(r.json().get('state', {}).get('unreadCount', 0) or 0)
        except Exception:
            initial_unread = 0

    print(f"Initial unreadCount: {initial_unread}")

    # 3) Send a DM to the same user (or change to another user id if available)
    send_payload = {
        "recipient_id": user_id,
        "body": f"Tinker test message {uuid.uuid4()}",
        "offline_id": str(uuid.uuid4())
    }
    r = requests.post(f"{BASE_URL}/chat/send", json=send_payload, headers=headers, verify=False)
    print_response('Send DM', r)

    # 4) Read chat state again — unreadCount should have incremented
    r = requests.get(f"{BASE_URL}/chat/state", headers=headers, verify=False)
    print_response('Post-send chat state', r)
    after_unread = None
    if r.status_code == 200:
        try:
            after_unread = int(r.json().get('state', {}).get('unreadCount', 0) or 0)
        except Exception:
            after_unread = None

    print(f"Unread before: {initial_unread}  after: {after_unread}")

    if after_unread is not None:
        if after_unread >= initial_unread + 1:
            print("SUCCESS: unreadCount incremented by the send action.")
        else:
            print("NOTE: unreadCount did not increment as expected. This may be because the server increments the recipient file (if sending to yourself it may behave differently), or because the state file is read from a different scope/team. Use the chat-tinker UI to inspect the per-user state file directly.")

    print("\nYou can also use the tinker UI at /notifications/chat-tinker (web UI) to read and manipulate per-user chat state files.")


if __name__ == '__main__':
    main()
