from app import create_app
from app.models import Match, Event, ScoutingData, TeamAllianceStatus, ScoutingAlliance
from app.utils.team_isolation import filter_matches_by_scouting_team, filter_events_by_scouting_team, get_current_scouting_team_number, get_alliance_team_numbers, get_alliance_shared_event_codes
from flask import g

app = create_app()
ctx = app.app_context()
ctx.push()

# Test as team 0
g.scouting_team_number = 0

print(f'\n=== Testing Filters for Team {get_current_scouting_team_number()} ===')
print(f'Alliance teams: {get_alliance_team_numbers()}')
print(f'Shared events: {get_alliance_shared_event_codes()}')

print(f'\n=== Database Stats ===')
print(f'Total matches in DB: {Match.query.count()}')
print(f'Total events in DB: {Event.query.count()}')
print(f'Total scouting data in DB: {ScoutingData.query.count()}')

print(f'\n=== Match Details ===')
for m in Match.query.limit(5).all():
    print(f'  Match {m.id}: scouting_team={m.scouting_team_number}, event_id={m.event_id}')

print(f'\n=== Event Details ===')
for e in Event.query.all():
    print(f'  Event {e.id}: code={e.code}, scouting_team={e.scouting_team_number}')

print(f'\n=== Filtered Results ===')
filtered_matches = filter_matches_by_scouting_team()
print(f'Filtered matches: {filtered_matches.count()}')

filtered_events = filter_events_by_scouting_team()
print(f'Filtered events: {filtered_events.count()}')

print(f'\n=== Alliance Info ===')
active_alliance = TeamAllianceStatus.get_active_alliance_for_team(0)
if active_alliance:
    print(f'Active alliance found: {active_alliance.alliance_id}')
    alliance = ScoutingAlliance.query.get(active_alliance.alliance_id)
    if alliance:
        print(f'Alliance name: {alliance.name}')
        print(f'Members: {alliance.get_member_team_numbers()}')
        print(f'Shared events: {alliance.get_shared_events()}')
else:
    print('No active alliance')
