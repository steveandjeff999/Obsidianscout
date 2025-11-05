"""
Single graph test with full logging
"""
import requests
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = 'https://localhost:8080'
API_BASE = f"{BASE_URL}/api/mobile"

# Login
print("Logging in...")
r = requests.post(f"{API_BASE}/auth/login", json={"username": "admin", "password": "5454", "team_number": 5454}, verify=False)
r.raise_for_status()
token = r.json()['token']
print(f"Got token: {token[:20]}...")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Request a simple graph for team 2583 with total_points
payload = {
    "team_numbers": [2583],
    "graph_type": "line",
    "metric": "total_points",
    "mode": "match_by_match"
}

print(f"\nRequesting graph with payload:")
print(json.dumps(payload, indent=2))

r = requests.post(f"{API_BASE}/graphs/visualize", json=payload, headers=headers, verify=False, timeout=30)

print(f"\nResponse status: {r.status_code}")
print(f"Content-Type: {r.headers.get('Content-Type')}")
print(f"Content length: {len(r.content)} bytes")

if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
    with open('tools/test_single_output.png', 'wb') as f:
        f.write(r.content)
    print("Saved to tools/test_single_output.png")
else:
    print(f"Response body: {r.text[:500]}")

print("\n** Check the Flask server console for detailed logs **")
