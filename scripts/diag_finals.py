"""Diagnostic: fetch 2026week0 playoffs from TBA and FIRST to compare alliance data."""
import requests, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TBA_KEY = 'hae7pfixkaYpROTHhMx6XQ5qLkjT5v7jX7IymIp3sFadVOTsboxkSVJlYu4yoq9a'

print("=== TBA sf + f matches for 2026week0 ===")
resp = requests.get('https://www.thebluealliance.com/api/v3/event/2026week0/matches',
                    headers={'X-TBA-Auth-Key': TBA_KEY})
tba_matches = resp.json()
for m in sorted(tba_matches, key=lambda x: (x.get('comp_level',''), x.get('set_number',0), x.get('match_number',0))):
    cl = m.get('comp_level', '')
    if cl not in ('sf', 'f'):
        continue
    sn = m.get('set_number', 0)
    mn = m.get('match_number', 0)
    red  = [t.replace('frc','') for t in m.get('alliances',{}).get('red',{}).get('team_keys',[])]
    blue = [t.replace('frc','') for t in m.get('alliances',{}).get('blue',{}).get('team_keys',[])]
    print(f"  {m['key']:22s}  cl={cl} sn={sn} mn={mn}  red={red}  blue={blue}")

# ---- FIRST API ----
print()
print("=== FIRST API playoffs for 2026week0 ===")
try:
    # Load app config to get FIRST credentials
    with open('app_config.json') as f:
        cfg = json.load(f)
    first_user = cfg.get('first_api_username', '')
    first_token = cfg.get('first_api_token', '')
    if not first_user or not first_token:
        print("  (no FIRST credentials in app_config.json)")
    else:
        import base64
        creds = base64.b64encode(f"{first_user}:{first_token}".encode()).decode()
        r = requests.get(
            'https://frc-api.firstinspires.org/v3.0/2026/schedule/week0?tournamentLevel=Playoff',
            headers={'Authorization': f'Basic {creds}', 'If-Modified-Since': ''}
        )
        if r.ok:
            sched = r.json()
            for m in sched.get('Schedule', []):
                mn = m.get('matchNumber', 0)
                teams = m.get('teams', [])
                red  = [str(t['teamNumber']) for t in teams if t.get('station','').startswith('Red')]
                blue = [str(t['teamNumber']) for t in teams if t.get('station','').startswith('Blue')]
                print(f"  Match {mn:3d}  red={red}  blue={blue}")
        else:
            print(f"  FIRST API error: {r.status_code} {r.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")
