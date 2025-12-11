#!/usr/bin/env python3
"""
Simple script to log in to the mobile API and print game & pit configurations
for both the active (team or alliance) and explicit per-team file.

Defaults target https://localhost:8080 using provided credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import requests
import urllib3


def disable_warnings() -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login(base_url: str, username: str, password: str, team_number: int, verify: bool) -> Optional[str]:
    url = f"{base_url}/auth/login"
    payload = {"username": username, "password": password, "team_number": team_number}
    r = requests.post(url, json=payload, verify=verify, timeout=10)
    if r.status_code != 200:
        print(f"Login failed ({r.status_code}): {r.text}")
        return None
    try:
        data = r.json()
        return data.get("token")
    except Exception:
        print("Login response not JSON or missing token")
        return None


def fetch_json(base_url: str, path: str, token: str, params: dict | None = None, headers: dict | None = None, verify: bool = False) -> None:
    url = f"{base_url}{path}"
    h = {"Authorization": f"Bearer {token}"}
    if headers:
        h.update(headers)
    r = requests.get(url, headers=h, params=params, verify=verify, timeout=10)
    print("\n==============================================")
    print(f"GET {r.request.url} -> {r.status_code}")
    try:
        print(json.dumps(r.json(), indent=2))
    except Exception:
        print(r.text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch mobile game/pit configs (active vs team)")
    parser.add_argument("--base-url", default="https://localhost:8080/api/mobile", help="Mobile API base URL (default: https://localhost:8080/api/mobile)")
    parser.add_argument("--username", default="Seth Herod", help="Username (default Seth Herod)")
    parser.add_argument("--password", default="5454", help="Password (default 5454)")
    parser.add_argument("--team", default=5454, type=int, help="Team number to request as token (default 5454)")
    parser.add_argument("--verify", action="store_true", help="Enable TLS certificate validation")
    args = parser.parse_args()

    disable_warnings()

    token = login(args.base_url, args.username, args.password, args.team, verify=args.verify)
    if not token:
        return 1

    # Endpoints to fetch
    # Active configs
    fetch_json(args.base_url, "/config/game", token, verify=args.verify)
    fetch_json(args.base_url, "/config/game/active", token, verify=args.verify)
    fetch_json(args.base_url, "/config/pit", token, verify=args.verify)
    fetch_json(args.base_url, "/config/pit/active", token, verify=args.verify)

    # Explicit per-team config: pass team override via query param and header
    team_param = {"team_number": args.team}
    fetch_json(args.base_url, "/config/game/team", token, params=team_param, verify=args.verify)
    fetch_json(args.base_url, "/config/pit/team", token, params={"team": args.team}, verify=args.verify)

    # Also show using X-Mobile-Requested-Team header explicitly
    header_override = {"X-Mobile-Requested-Team": str(args.team)}
    fetch_json(args.base_url, "/config/game/team", token, headers=header_override, verify=args.verify)
    fetch_json(args.base_url, "/config/pit/team", token, headers=header_override, verify=args.verify)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
