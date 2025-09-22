"""Validate API keys found in configs and do a lightweight API probe.

Usage: python tests/validate_api_keys.py [--team TEAM_NUMBER]

This script searches for game config files (team-specific and defaults), reports
where TBA and FIRST API keys are found (masked), and makes a small request to
each service to show HTTP status and a short response message for debugging.
"""
import os
import json
import glob
import argparse
import requests


def mask(val):
    if not val:
        return None
    s = str(val)
    if len(s) <= 6:
        return '*' * len(s)
    return s[:3] + '...' + s[-3:]


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return None


def find_configs():
    base = os.getcwd()
    results = []

    # global config
    gpath = os.path.join(base, 'config', 'game_config.json')
    if os.path.exists(gpath):
        results.append(('global', gpath, load_json(gpath)))

    # default year configs
    default_dir = os.path.join(base, 'instance', 'defaultconfigs', 'years')
    if os.path.isdir(default_dir):
        for p in glob.glob(os.path.join(default_dir, '*.json')):
            results.append(('default', p, load_json(p)))

    # team-specific
    team_dir = os.path.join(base, 'instance', 'configs')
    if os.path.isdir(team_dir):
        for team_path in glob.glob(os.path.join(team_dir, '*', 'game_config.json')):
            parts = team_path.split(os.sep)
            team = os.path.basename(os.path.dirname(team_path))
            results.append((f'team:{team}', team_path, load_json(team_path)))

    return results


def probe_tba(key):
    url = 'https://www.thebluealliance.com/api/v3/status'
    headers = {'X-TBA-Auth-Key': key, 'User-Agent': 'FRC-Scouting-Platform/1.0', 'Accept': 'application/json'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.status_code, r.text[:300]
    except Exception as e:
        return None, str(e)


def probe_first(username, token, base_url, season=2025):
    # Try a harmless endpoint used elsewhere in the project
    url = f"{base_url}/v2.0/{season}/events"
    # Build Basic auth header
    import base64
    auth_string = f"{username}:{token}" if username else f":{token}"
    b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
    headers = {'Authorization': f'Basic {b64}', 'Accept': 'application/json'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return r.status_code, r.text[:300]
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--team', help='Team number to inspect team-specific config')
    args = parser.parse_args()

    configs = find_configs()

    print('Found configs:')
    for which, path, data in configs:
        print(f' - {which}: {path} (loaded: {bool(data)})')

    # If user asked for specific team, filter
    if args.team:
        configs = [c for c in configs if c[0] == f'team:{args.team}']
        if not configs:
            print(f'No team-specific config found for {args.team}')
            return

    # Inspect each config for keys
    for which, path, data in configs:
        if not data:
            continue
        print(f'\nInspecting {which} ({path})')
        tba = data.get('tba_api_settings', {})
        api = data.get('api_settings', {})
        ta = tba.get('auth_key') if isinstance(tba, dict) else None
        fa = api.get('auth_token') if isinstance(api, dict) else None
        uname = api.get('username') if isinstance(api, dict) else None

        print('  TBA auth_key:', mask(ta))
        print('  FIRST auth_token:', mask(fa))
        print('  FIRST username:', uname)

        if ta:
            code, body = probe_tba(ta)
            print(f'  TBA probe -> status: {code}, body: {body}')
        else:
            print('  No TBA key present; skipping TBA probe')

        if fa:
            base_url = data.get('tba_api_settings', {}).get('base_url') or data.get('api_settings', {}).get('base_url') or 'https://frc-api.firstinspires.org'
            code, body = probe_first(uname, fa, base_url, season=data.get('season', 2025))
            print(f'  FIRST probe -> status: {code}, body: {body}')
        else:
            print('  No FIRST auth token present; skipping FIRST probe')


if __name__ == '__main__':
    main()
