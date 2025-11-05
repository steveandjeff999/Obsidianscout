"""
Test login and decode JWT to see what team_number is in the token
"""
import requests
import json
import urllib3
import jwt

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = 'https://localhost:8080'
API_BASE = f"{BASE_URL}/api/mobile"

# Login as admin
login_payload = {"username": "admin", "password": "5454", "team_number": 5454}
r = requests.post(f"{API_BASE}/auth/login", json=login_payload, verify=False)

print("Login Response:")
print(f"Status: {r.status_code}")
resp_data = r.json()
print(json.dumps(resp_data, indent=2))

if resp_data.get('success') and resp_data.get('token'):
    token = resp_data['token']
    
    # Decode without verification to see payload
    print("\n" + "="*60)
    print("JWT Token Payload (decoded):")
    print("="*60)
    decoded = jwt.decode(token, options={"verify_signature": False})
    print(json.dumps(decoded, indent=2))
    
    print("\n" + "="*60)
    print("Key fields:")
    print(f"  user_id: {decoded.get('user_id')}")
    print(f"  username: {decoded.get('username')}")
    print(f"  team_number: {decoded.get('team_number')}")
    print("="*60)
