#!/usr/bin/env python3
"""
Simple helper script to call the mobile API and print the pit configuration.

Usage examples:
  # Login using team_number/password via env vars
  MOBILE_API_BASE=https://localhost:8080 TEAM_NUMBER=5454 PASSWORD=5454 python tools/fetch_pit_config.py

  # Use an existing token in an env var
  MOBILE_API_BASE=https://localhost:8080 TOKEN=<your_token> python tools/fetch_pit_config.py

The script prints a short, human-readable summary of the pit configuration
and dumps the full JSON when available.
"""
import os
import sys
import json
import argparse

try:
    import requests
except Exception:
    print("This script requires the 'requests' package. Install with: pip install requests")
    sys.exit(2)

MOBILE_API_BASE='https://127.0.0.1:8080'
User_Name='Seth Herod'
TEAM_NUMBER=5454
PASSWORD=5454


def _read_first_existing_file(paths):
    for p in paths:
        if not p:
            continue
        p = os.path.expanduser(p)
        if os.path.exists(p) and os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8') as fh:
                    return fh.read().strip()
            except Exception:
                continue
    return None

def login_and_get_token(base, team_number=5454, password=5454, username='Seth Herod', verify=True):
    url = f"{base.rstrip('/')}/api/mobile/auth/login"
    payload = {}
    if username:
        payload['username'] = username
    if team_number is not None:
        payload['team_number'] = team_number
    payload['password'] = password or ''

    resp = requests.post(url, json=payload, timeout=10, verify=verify)
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError(f"Login error: {data}")
    return data.get('token')


def fetch_pit_config(base, token, verify=True):
    url = f"{base.rstrip('/')}/api/mobile/config/pit"
    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(url, headers=headers, timeout=10, verify=verify)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch pit config ({resp.status_code}): {resp.text}")
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description='Fetch mobile /config/pit JSON and print a short summary')
    parser.add_argument('--base', '-b', default=os.environ.get('MOBILE_API_BASE', MOBILE_API_BASE))
    parser.add_argument('--insecure', action='store_true', default=False, help='Disable SSL verification for self-signed certs')
    parser.add_argument('--token', '-t', default=os.environ.get('TOKEN'))
    parser.add_argument('--token-file', default=None, help='Path to a file containing the token')
    # Default to built-in values so the script logs in automatically
    # Default to built-in values (force these unless explicitly overridden)
    parser.add_argument('--team', '-n', default=str(TEAM_NUMBER))
    parser.add_argument('--password', '-p', default=str(PASSWORD))
    parser.add_argument('--password-file', default=None, help='Path to a file containing the password')
    # Force the exact username unless explicitly provided
    parser.add_argument('--username', '-u', default=User_Name)
    args = parser.parse_args()

    base = args.base
    token = args.token

    try:
        # Resolve token: command-line / env first, then token-file or common files
        if not token:
            token_paths = [args.token_file, 'token.txt', '.token', os.path.join('tools', 'token.txt'), os.path.expanduser('~/.obsidian_token')]
            token_from_file = _read_first_existing_file(token_paths)
            if token_from_file:
                token = token_from_file

        # Resolve password from CLI/env or files or module constant
        password = args.password
        if not password:
            password_paths = [args.password_file, 'password.txt', '.password', os.path.join('tools', 'password.txt'), os.path.expanduser('~/.obsidian_password')]
            password_from_file = _read_first_existing_file(password_paths)
            if password_from_file:
                password = password_from_file

        # Lastly, fall back to constants defined in this module (if present)
        if not password:
            try:
                password = PASSWORD
            except Exception:
                password = None

        if not token:
            if not password:
                raise RuntimeError('No token provided and no password available for login')
            # Use team number provided via args/env or the module constant
            team_num = args.team or os.environ.get('TEAM_NUMBER') or TEAM_NUMBER
            # Resolve username: CLI/env first, fallback to module constant
            username = args.username or os.environ.get('USERNAME') or globals().get('User_Name')
            # Convert team number to int when possible
            try:
                team_num_int = int(team_num) if team_num is not None else None
            except Exception:
                team_num_int = team_num

            # Decide SSL verification behavior. Default to disabling verification
            # for localhost/127.0.0.1 HTTPS to support self-signed dev certs.
            verify = not args.insecure
            if base.startswith('https://') and ('127.0.0.1' in base or 'localhost' in base) and not args.insecure:
                print('Detected local HTTPS host; disabling SSL verification for this run')
                verify = False

            print(f"Logging in to {base} as username={username!s} team={team_num_int!s} (verify={verify})")
            token = login_and_get_token(base, team_number=team_num_int, password=password, username=username, verify=verify)

        # Use same verification decision when fetching the config
        if 'verify' not in locals():
            verify = not args.insecure
            if base.startswith('https://') and ('127.0.0.1' in base or 'localhost' in base) and not args.insecure:
                verify = False

        data = fetch_pit_config(base, token, verify=verify)
        if not data.get('success'):
            print('API returned an error:', data)
            sys.exit(1)

        cfg = data.get('config') or {}

        # Print a short human-friendly summary
        print('Success: fetched pit config')
        title = cfg.get('pit_scouting', {}).get('title') if isinstance(cfg, dict) else None
        if title:
            print(f"Title: {title}")
        sections = cfg.get('pit_scouting', {}).get('sections') if isinstance(cfg, dict) else None
        if sections:
            print(f"Sections: {len(sections)}")

        # Pretty-print the full config as JSON
        print('\n--- Full JSON ---')
        print(json.dumps(cfg, indent=2, ensure_ascii=False))

    except Exception as e:
        print('Error:', e)
        sys.exit(1)


if __name__ == '__main__':
    main()
