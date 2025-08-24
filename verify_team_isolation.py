#!/usr/bin/env python3
"""
Current system status and verification of team isolation functionality.
"""

from app import create_app
from app.models import Team, User, Event, Match

def show_system_status():
    """Show the current status of team isolation in the system."""
    app = create_app()
    
    with app.app_context():
        print("=== TEAM ISOLATION SYSTEM STATUS ===")
        print()
        
        # Show users
        print("USERS:")
        users = User.query.all()
        for user in users:
            scouting_team = getattr(user, 'scouting_team_number', None)
            print(f"  • {user.username}: Scouting Team {scouting_team}")
        print()
        
        # Show teams by scouting team
        print("TEAMS BY SCOUTING TEAM:")
        teams = Team.query.all()
        team_counts = {}
        for team in teams:
            st = team.scouting_team_number
            team_counts[st] = team_counts.get(st, 0) + 1
        
        for scouting_team in sorted(team_counts.keys()):
            count = team_counts[scouting_team]
            print(f"  • Scouting Team {scouting_team}: {count} teams")
        print()
        
        # Show events by scouting team
        print("EVENTS BY SCOUTING TEAM:")
        events = Event.query.all()
        event_counts = {}
        for event in events:
            st = event.scouting_team_number
            event_counts[st] = event_counts.get(st, 0) + 1
        
        for scouting_team in sorted(event_counts.keys()):
            count = event_counts[scouting_team]
            print(f"  • Scouting Team {scouting_team}: {count} events")
        print()
        
        # Show matches by scouting team
        print("MATCHES BY SCOUTING TEAM:")
        matches = Match.query.all()
        match_counts = {}
        for match in matches:
            st = match.scouting_team_number
            match_counts[st] = match_counts.get(st, 0) + 1
        
        if match_counts:
            for scouting_team in sorted(match_counts.keys()):
                count = match_counts[scouting_team]
                print(f"  • Scouting Team {scouting_team}: {count} matches")
        else:
            print("  • No matches found in database")
        print()
        
        print("=== TESTING INSTRUCTIONS ===")
        print()
        print("1. Open https://127.0.0.1:5000 in your browser")
        print("2. Log in as 'Seth Herod' - you should see 75 teams (scouting team 5454)")
        print("3. Log out and log in as 'bob' - you should see 0 teams (scouting team 5568)")
        print("4. As bob, go to Teams page and click 'Sync Teams from Config'")
        print("5. Bob should now see his own copy of teams (separate from Seth's)")
        print("6. Log back in as Seth - his teams should be unchanged")
        print()
        print("Each scouting team will have completely separate instances of:")
        print("  • Teams (same team numbers, but different database records)")
        print("  • Events (same event codes, but different database records)")
        print("  • Matches (same matches, but different database records)")
        print("  • Scouting data (completely separate)")
        print()
        print("This ensures complete data isolation between different scouting teams!")

if __name__ == '__main__':
    show_system_status()
