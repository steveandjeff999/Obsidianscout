"""
Tinker-style test to verify the mobile react API returns Unicode emoji characters
in its JSON response (not escaped sequences).

Usage: run with the dev server running. This is a manual tinker script similar
to `test_tinker_graphs.py` and intended to be executed directly (not as a strict
pytest test).
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
    resp = requests.post(f"{BASE_URL}/auth/login", json={"username": TEST_USERNAME, "team_number": TEST_TEAM_NUMBER, "password": TEST_PASSWORD}, verify=False)
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

    # Find a recipient from /chat/members
    print('Fetching chat members...')
    m = requests.get(f"{BASE_URL}/chat/members?scope=team", headers=headers, verify=False)
    try:
        members = m.json().get('members') or []
    except Exception:
        print('Failed to parse members response:', m.text)
        members = []

    recipient_id = None
    if members:
        # members can be objects or strings; prefer object with id
        for mem in members:
            if isinstance(mem, dict) and mem.get('username') != TEST_USERNAME:
                recipient_id = mem.get('id')
                break
            if isinstance(mem, str) and mem != TEST_USERNAME:
                # Need to map username to id; fall back to first non-self string
                recipient_id = None
                break

    if recipient_id is None:
        print('No suitable recipient found in team members. Trying alliance message instead.')
        # Send an alliance message (group) so we can react to it — server will return a message dict
        send_payload = { 'conversation_type': 'alliance', 'body': 'Tinker alliance message for reaction test' }
        sent_type = 'alliance'
    else:
        send_payload = { 'recipient_id': recipient_id, 'body': 'Tinker DM message for reaction test' }
        sent_type = 'dm'

    print('Sending message...')
    s = requests.post(f"{BASE_URL}/chat/send", headers=headers, json=send_payload, verify=False)
    print(f"Send status: {s.status_code}")
    try:
        send_data = s.json()
    except Exception:
        print('Send response text:', s.text)
        return

    if not send_data.get('success'):
        print('Message send failed:', send_data)
        return

    # The send endpoint may return the saved message directly or a wrapper; try common shapes
    message = None
    if isinstance(send_data, dict) and send_data.get('message'):
        message = send_data.get('message')
    elif isinstance(send_data, dict) and send_data.get('id'):
        message = send_data
    else:
        for v in send_data.values() if isinstance(send_data, dict) else []:
            if isinstance(v, dict) and v.get('id'):
                message = v
                break

    if not message:
        print('Could not locate saved message in send response:', send_data)
        return

    message_id = message.get('id')
    print('Message sent with id:', message_id)

    # React to the message with a Unicode emoji
    emoji = '👍'
    print(f"Reacting to message {message_id} with emoji {emoji}")
    r = requests.post(f"{BASE_URL}/chat/react-message", headers=headers, json={'message_id': message_id, 'emoji': emoji}, verify=False)
    print('React status:', r.status_code)
    # Print raw text so we can see unicode characters as sent by server
    print('Raw response text:')
    print(r.text)

    try:
        j = r.json()
        print('Parsed JSON response:')
        print(json.dumps(j, ensure_ascii=False, indent=2))
    except Exception:
        print('Failed to parse JSON response')

    # Fetch messages from server to verify reactions persisted and are returned as unicode
    print('\nFetching messages to verify reaction persistence...')
    if sent_type == 'dm' and recipient_id:
        msgs_resp = requests.get(f"{BASE_URL}/chat/messages?type=dm&user={recipient_id}", headers=headers, verify=False)
    else:
        msgs_resp = requests.get(f"{BASE_URL}/chat/messages?type=alliance", headers=headers, verify=False)

    print('Messages fetch status:', msgs_resp.status_code)
    try:
        msgs_json = msgs_resp.json()
    except Exception:
        print('Failed to parse messages response:', msgs_resp.text)
        return

    # messages may be under 'messages' key or be a list directly
    messages_list = None
    if isinstance(msgs_json, dict) and msgs_json.get('messages'):
        messages_list = msgs_json.get('messages')
    elif isinstance(msgs_json, list):
        messages_list = msgs_json
    else:
        # Try common alternative keys
        for k in ('data', 'results', 'history'):
            if isinstance(msgs_json.get(k), list):
                messages_list = msgs_json.get(k)
                break

    if not messages_list:
        print('No messages list found in response:', json.dumps(msgs_json, ensure_ascii=False, indent=2))
        return

    # Find our message by id
    found = None
    for m in messages_list:
        if isinstance(m, dict) and m.get('id') == message_id:
            found = m
            break

    if not found:
        print('Sent message not found in fetched messages. Showing most recent messages:')
        print(json.dumps(messages_list[:5], ensure_ascii=False, indent=2))
        return

    print('Found message:')
    # Print the message object with unicode preserved
    print(json.dumps(found, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
