#!/usr/bin/env python3
"""
Full-Featured API Test Script
Tests the enhanced API endpoints that provide access to all data
"""

import requests
import json
import sys
import urllib3
from datetime import datetime

# Disable SSL warnings for localhost testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class APITester:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.verify = False

    def test_endpoint(self, endpoint, method='GET', data=None, params=None):
        """Test a specific API endpoint"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            print(f"\n### Testing {method} {endpoint} ###")
            
            if method == 'GET':
                response = self.session.get(url, params=params)
            elif method == 'POST':
                response = self.session.post(url, json=data, params=params)
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"Success: {json.dumps(result, indent=2)}")
                return result
            else:
                print(f"Error: {response.text}")
                return None
                
        except Exception as e:
            print(f"Exception: {str(e)}")
            return None

    def run_comprehensive_test(self):
        """Run comprehensive API tests"""
        print("=" * 80)
        print("FULL-FEATURED API COMPREHENSIVE TEST")
        print(f"Base URL: {self.base_url}")
        print(f"API Key: {self.api_key[:20]}...")
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        # Test API info
        info = self.test_endpoint('/info')
        
        # Test all teams
        print("\n" + "="*50)
        print("TESTING ALL TEAMS ACCESS")
        teams = self.test_endpoint('/teams')
        if teams and 'teams' in teams:
            print(f"Total teams found: {teams.get('total_count', len(teams['teams']))}")
            
            # Test team filtering by team number
            if teams['teams']:
                sample_team = teams['teams'][0]
                print(f"\nTesting team number filter for team {sample_team['team_number']}:")
                filtered_teams = self.test_endpoint('/teams', params={'team_number': sample_team['team_number']})
                
                # Test team details
                print(f"\nTesting team details for team ID {sample_team['id']}:")
                team_details = self.test_endpoint(f"/teams/{sample_team['id']}")

        # Test all events
        print("\n" + "="*50)
        print("TESTING ALL EVENTS ACCESS")
        events = self.test_endpoint('/events')
        if events and 'events' in events:
            print(f"Total events found: {events.get('total_count', len(events['events']))}")
            
            # Test event details
            if events['events']:
                sample_event = events['events'][0]
                print(f"\nTesting event details for event ID {sample_event['id']}:")
                event_details = self.test_endpoint(f"/events/{sample_event['id']}")

        # Test all matches
        print("\n" + "="*50)
        print("TESTING ALL MATCHES ACCESS")
        matches = self.test_endpoint('/matches')
        if matches and 'matches' in matches:
            print(f"Total matches found: {matches.get('total_count', len(matches['matches']))}")
            
            # Test match filtering
            if events and events.get('events'):
                event_id = events['events'][0]['id']
                print(f"\nTesting match filtering by event ID {event_id}:")
                event_matches = self.test_endpoint('/matches', params={'event_id': event_id})
                
            # Test match details
            if matches['matches']:
                sample_match = matches['matches'][0]
                print(f"\nTesting match details for match ID {sample_match['id']}:")
                match_details = self.test_endpoint(f"/matches/{sample_match['id']}")

        # Test scouting data
        print("\n" + "="*50)
        print("TESTING ALL SCOUTING DATA ACCESS")
        scouting_data = self.test_endpoint('/scouting-data')
        if scouting_data:
            print(f"Total scouting data found: {scouting_data.get('total_count', len(scouting_data.get('scouting_data', [])))}")

        # Test analytics
        print("\n" + "="*50)
        print("TESTING ANALYTICS ACCESS")
        if teams and teams.get('teams'):
            sample_team = teams['teams'][0]
            print(f"Testing analytics for team {sample_team['team_number']} (ID: {sample_team['id']}):")
            analytics = self.test_endpoint('/analytics/team-performance', params={'team_number': sample_team['team_number']})

        # Test sync status
        print("\n" + "="*50)
        print("TESTING SYNC STATUS")
        sync_status = self.test_endpoint('/sync/status')

        # Test health check
        print("\n" + "="*50)
        print("TESTING HEALTH CHECK")
        health = self.test_endpoint('/health')

        print("\n" + "="*80)
        print("COMPREHENSIVE API TEST COMPLETE")
        print("="*80)

def main():
    # Configuration
    BASE_URL = "https://127.0.0.1:8080/api/v1"
    
    # Get API key from user
    if len(sys.argv) > 1:
        API_KEY = sys.argv[1]
    else:
        API_KEY = input("Enter your API key: ").strip()
    
    if not API_KEY:
        print("Error: API key is required")
        sys.exit(1)
    
    # Run tests
    tester = APITester(BASE_URL, API_KEY)
    tester.run_comprehensive_test()

if __name__ == "__main__":
    main()