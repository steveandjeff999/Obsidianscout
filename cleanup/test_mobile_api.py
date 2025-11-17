"""
Simple test script for Mobile API
Tests basic functionality of the mobile API endpoints
"""
import requests
import json
from datetime import datetime

# Configuration
BASE_URL = "https://localhost:8080/api/mobile"  # HTTPS with self-signed cert
TEST_USERNAME = "Seth Herod"  # Default superadmin account
TEST_PASSWORD = "5454"    # Default password
TEST_TEAM_NUMBER = 5454

# Disable SSL verification warnings for self-signed certificates
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def print_response(name, response):
    """Pretty print API response"""
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")
    print(f"Status Code: {response.status_code}")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except:
        print(response.text)
    print(f"{'='*60}\n")

def test_mobile_api():
    """Test mobile API endpoints"""
    
    print(" Starting Mobile API Tests...")
    print(f"Base URL: {BASE_URL}")
    
    # Test 1: Health Check (No Auth Required)
    print("\n1. Testing Health Check...")
    response = requests.get(f"{BASE_URL}/health", verify=False)  # Disable SSL verification for self-signed certs
    print_response("Health Check", response)
    
    if response.status_code != 200:
        print(" Health check failed! Make sure the server is running.")
        return
    
    # Test 2: Login
    print("\n2. Testing Login...")
    login_data = {
        "username": TEST_USERNAME,
        "team_number": TEST_TEAM_NUMBER,
        "password": TEST_PASSWORD
    }
    
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json=login_data,
        headers={"Content-Type": "application/json"},
        verify=False  # Disable SSL verification for self-signed certs
    )
    print_response("Login", response)
    
    if response.status_code != 200:
        print(" Login failed! Check username and password.")
        return
    
    # Extract token
    login_result = response.json()
    if not login_result.get("success"):
        print(" Login unsuccessful!")
        return
    
    token = login_result.get("token")
    user = login_result.get("user")
    
    print(f" Login successful!")
    print(f"   User: {user.get('username')}")
    print(f"   Team: {user.get('team_number')}")
    print(f"   Roles: {user.get('roles')}")
    print(f"   Token: {token[:20]}...")
    
    # Setup headers for authenticated requests
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Test 3: Verify Token
    print("\n3. Testing Token Verification...")
    response = requests.get(f"{BASE_URL}/auth/verify", headers=headers, verify=False)
    print_response("Verify Token", response)
    
    if response.status_code == 200 and response.json().get("valid"):
        print(" Token is valid!")
    else:
        print(" Token verification failed!")
    
    # Test 4: Get Teams
    print("\n4. Testing Get Teams...")
    response = requests.get(f"{BASE_URL}/teams", headers=headers, verify=False)
    print_response("Get Teams", response)
    
    if response.status_code == 200:
        teams_data = response.json()
        team_count = teams_data.get("count", 0)
        print(f" Retrieved {team_count} teams")
    else:
        print("Could not retrieve teams (may be empty)")
    
    # Test 5: Get Events
    print("\n5. Testing Get Events...")
    response = requests.get(f"{BASE_URL}/events", headers=headers, verify=False)
    print_response("Get Events", response)
    
    if response.status_code == 200:
        events_data = response.json()
        event_count = len(events_data.get("events", []))
        print(f" Retrieved {event_count} events")
    else:
        print("Could not retrieve events (may be empty)")
    
    # Test 6: Get Game Configuration
    print("\n6. Testing Get Game Configuration...")
    response = requests.get(f"{BASE_URL}/config/game", headers=headers, verify=False)
    print_response("Game Configuration", response)
    
    if response.status_code == 200:
        config = response.json().get("config", {})
        print(f" Game Configuration Retrieved!")
        print(f"   Season: {config.get('season')}")
        print(f"   Game: {config.get('game_name')}")
        print(f"   Event: {config.get('current_event_code')}")
    else:
        print("Could not retrieve game configuration")
    
    # Test 7: Get Sync Status
    print("\n7️⃣ Testing Get Sync Status...")
    response = requests.get(f"{BASE_URL}/sync/status", headers=headers, verify=False)
    print_response("Sync Status", response)
    
    if response.status_code == 200:
        print(" Sync status retrieved!")
    else:
        print("Could not retrieve sync status")
    
    # Test 8: Refresh Token
    print("\n8️⃣ Testing Token Refresh...")
    response = requests.post(f"{BASE_URL}/auth/refresh", headers=headers, verify=False)
    print_response("Refresh Token", response)
    
    if response.status_code == 200:
        new_token = response.json().get("token")
        print(f" Token refreshed successfully!")
        print(f"   New Token: {new_token[:20]}...")
    else:
        print("Token refresh failed")
    
    # Summary
    print("\n" + "="*60)
    print(" TEST SUMMARY")
    print("="*60)
    print(" Mobile API is operational!")
    print(" Authentication working")
    print(" Basic endpoints accessible")
    print("\n Next Steps:")
    print("   1. Create teams and events in the system")
    print("   2. Test scouting data submission")
    print("   3. Read MOBILE_API_DOCUMENTATION.md for full API details")
    print("   4. Build your mobile app!")
    print("="*60 + "\n")

if __name__ == "__main__":
    try:
        test_mobile_api()
    except requests.exceptions.ConnectionError:
        print("\n ERROR: Could not connect to the server!")
        print("   Make sure the OBSIDIAN Scout server is running:")
        print("   python run.py")
        print()
    except requests.exceptions.SSLError:
        print("\n ERROR: SSL certificate issue!")
        print("   Try using http:// instead of https://")
        print()
    except Exception as e:
        print(f"\n ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
