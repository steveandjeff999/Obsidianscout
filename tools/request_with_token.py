"""
Simple script to call GET /api/mobile/config/game using a provided JWT token
and print the HTTP status, response headers, and body. Useful for debugging
which config is returned for a given token.

Usage (PowerShell):
    & ".\.venv\Scripts\Activate.ps1"
    python tools\request_with_token.py

You can also set MOBILE_API_BASE to point to a running server (default http://localhost:8080).
"""
import os
import requests
import urllib3
import json

# Suppress warnings for self-signed certs in dev
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = os.environ.get('MOBILE_API_BASE', 'http://localhost:8080')
URL = f"{API_BASE}/api/mobile/config/game"

# Token provided by user
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjo0LCJ1c2VybmFtZSI6IlNldGggSGVyb2QiLCJ0ZWFtX251bWJlciI6Njg3OSwiZXhwIjoxNzYyNTUxMzA4LCJpYXQiOjE3NjI0NjQ5MDh9.hAmjtNm9H-9i9fh3iQN9X0T2iZt6lRljjvR43wUp7oA"

HEADERS = {
    'Authorization': f'Bearer {TOKEN}',
    'Accept': 'application/json'
}

print(f"Requesting: {URL}")
print(f"Using token (first 40 chars): {TOKEN[:40]}...")

try:
    resp = requests.get(URL, headers=HEADERS, verify=False, timeout=10)
except Exception as e:
    print(f"Request failed: {e}")
    raise SystemExit(1)

print('\n=== HTTP STATUS ===')
print(resp.status_code)

print('\n=== RESPONSE HEADERS ===')
for k, v in resp.headers.items():
    print(f"{k}: {v}")

print('\n=== RESPONSE BODY ===')
ct = resp.headers.get('Content-Type','')
if 'application/json' in ct:
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)
else:
    print(resp.text)

# Exit code 0 on 2xx, otherwise 1 to indicate failure
if 200 <= resp.status_code < 300:
    raise SystemExit(0)
else:
    raise SystemExit(1)
