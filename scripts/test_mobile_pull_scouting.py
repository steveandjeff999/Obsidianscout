#!/usr/bin/env python3
"""Test script to login to the mobile API and pull scouting data.

Usage examples:
  python scripts/test_mobile_pull_scouting.py --url http://localhost:8080 --username admin --password secret --endpoint history
  python scripts/test_mobile_pull_scouting.py --url http://localhost:8080 --username scout1 --password secret --endpoint all --team 5454 --limit 100 --out scouting.json

This script:
  - POSTs to /api/mobile/auth/login with JSON {username,password[,team_number]}
  - Extracts the returned token
  - Uses the token as Bearer in Authorization header to call a selected endpoint
  - Prints or saves the JSON response

Notes:
  - Requires `requests` (already in project requirements)
  - If your server uses HTTPS with an internal/self-signed cert, use --insecure to skip verify
"""

from __future__ import annotations
import argparse
import json
import sys
from typing import Optional
import requests

LOGIN_PATH = "/api/mobile/auth/login"
ENDPOINTS = {
    "history": "/api/mobile/scouting/history",
    "all": "/api/mobile/scouting/all",
}


def login(base_url: str, username: str, password: str, team: Optional[str], verify: bool = True):
    url = base_url.rstrip("/") + LOGIN_PATH
    payload = {"username": username, "password": password}
    if team is not None:
        payload["team_number"] = team
    r = requests.post(url, json=payload, verify=verify, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Login failed: {data}")
    token = data.get("token")
    if not token:
        raise RuntimeError("Login response did not include token")
    return token, data


def fetch_with_token(base_url: str, token: str, endpoint: str, params: dict, verify: bool = True):
    url = base_url.rstrip("/") + endpoint
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, params=params, verify=verify, timeout=20)
    r.raise_for_status()
    return r.json()


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, scrolledtext
    except Exception as e:
        print("Tkinter is not available on this system:", e, file=sys.stderr)
        sys.exit(1)

    root = tk.Tk()
    root.title("Mobile API Scouting Puller")

    frm = ttk.Frame(root, padding=10)
    frm.grid(row=0, column=0, sticky=(tk.N, tk.S, tk.E, tk.W))

    # Inputs
    row = 0
    ttk.Label(frm, text="Server URL:").grid(row=row, column=0, sticky=tk.W)
    url_entry = ttk.Entry(frm, width=50)
    url_entry.grid(row=row, column=1, sticky=(tk.W, tk.E))
    url_entry.insert(0, "http://localhost:8080")

    row += 1
    ttk.Label(frm, text="Username:").grid(row=row, column=0, sticky=tk.W)
    username_entry = ttk.Entry(frm, width=30)
    username_entry.grid(row=row, column=1, sticky=(tk.W, tk.E))

    row += 1
    ttk.Label(frm, text="Password:").grid(row=row, column=0, sticky=tk.W)
    password_entry = ttk.Entry(frm, width=30, show="*")
    password_entry.grid(row=row, column=1, sticky=(tk.W, tk.E))

    row += 1
    ttk.Label(frm, text="Team (optional):").grid(row=row, column=0, sticky=tk.W)
    team_entry = ttk.Entry(frm, width=20)
    team_entry.grid(row=row, column=1, sticky=(tk.W, tk.E))

    row += 1
    ttk.Label(frm, text="Endpoint:").grid(row=row, column=0, sticky=tk.W)
    endpoint_var = tk.StringVar(value="history")
    endpoint_combo = ttk.Combobox(frm, textvariable=endpoint_var, values=list(ENDPOINTS.keys()), state="readonly", width=10)
    endpoint_combo.grid(row=row, column=1, sticky=(tk.W, tk.E))

    row += 1
    limit_var = tk.StringVar()
    offset_var = tk.StringVar()
    ttk.Label(frm, text="Limit:").grid(row=row, column=0, sticky=tk.W)
    limit_entry = ttk.Entry(frm, textvariable=limit_var, width=10)
    limit_entry.grid(row=row, column=1, sticky=tk.W)
    ttk.Label(frm, text="Offset:").grid(row=row, column=1, sticky=tk.E)
    offset_entry = ttk.Entry(frm, textvariable=offset_var, width=10)
    offset_entry.grid(row=row, column=1, sticky=tk.E, padx=(0, 120))

    row += 1
    insecure_var = tk.BooleanVar(value=False)
    insecure_check = ttk.Checkbutton(frm, text="Insecure (skip TLS verify)", variable=insecure_var)
    insecure_check.grid(row=row, column=0, columnspan=2, sticky=tk.W)

    row += 1
    ttk.Label(frm, text="Save output to:").grid(row=row, column=0, sticky=tk.W)
    out_entry = ttk.Entry(frm, width=40)
    out_entry.grid(row=row, column=1, sticky=(tk.W, tk.E))
    def choose_file():
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files","*.json"), ("All files","*.*")])
        if p:
            out_entry.delete(0, tk.END)
            out_entry.insert(0, p)
    ttk.Button(frm, text="Browse", command=choose_file).grid(row=row, column=2, sticky=tk.W)

    row += 1
    status_var = tk.StringVar(value="Ready")
    status_label = ttk.Label(frm, textvariable=status_var)
    status_label.grid(row=row, column=0, columnspan=3, sticky=(tk.W, tk.E))

    row += 1
    output = scrolledtext.ScrolledText(frm, width=80, height=20)
    output.grid(row=row, column=0, columnspan=3, pady=(10, 0))

    def set_status(s):
        root.after(0, status_var.set, s)

    def append_output(text):
        def _():
            output.delete('1.0', tk.END)
            output.insert(tk.END, text)
        root.after(0, _)

    def disable_controls():
        fetch_btn.config(state=tk.DISABLED)
    def enable_controls():
        fetch_btn.config(state=tk.NORMAL)

    def do_fetch_thread():
        try:
            set_status("Logging in...")
            token, _ = login(url_entry.get(), username_entry.get(), password_entry.get(), team_entry.get() or None, verify=not insecure_var.get())
            set_status("Logged in; fetching data...")
            params = {}
            if limit_var.get():
                try:
                    params['limit'] = int(limit_var.get())
                except Exception:
                    pass
            if offset_var.get():
                try:
                    params['offset'] = int(offset_var.get())
                except Exception:
                    pass
            if team_entry.get() and endpoint_var.get() == 'all':
                params['team_number'] = team_entry.get()

            resp = fetch_with_token(url_entry.get(), token, ENDPOINTS[endpoint_var.get()], params, verify=not insecure_var.get())
            out_text = json.dumps(resp, indent=2, ensure_ascii=False)
            append_output(out_text)
            if out_entry.get():
                with open(out_entry.get(), 'w', encoding='utf-8') as fh:
                    fh.write(out_text)
                set_status(f"Saved to {out_entry.get()}")
            else:
                set_status("Done")
        except requests.HTTPError as he:
            try:
                err = he.response.json()
            except Exception:
                err = he.response.text if he.response is not None else str(he)
            append_output(str(err))
            set_status("HTTP error")
        except Exception as e:
            append_output(str(e))
            set_status("Error")
        finally:
            enable_controls()

    def on_fetch():
        output.delete('1.0', tk.END)
        disable_controls()
        set_status('Starting...')
        import threading
        t = threading.Thread(target=do_fetch_thread, daemon=True)
        t.start()

    def on_save_output():
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files","*.json"), ("All files","*.*")])
        if p:
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(output.get('1.0', tk.END))
            set_status(f"Saved to {p}")

    btn_frm = ttk.Frame(frm)
    btn_frm.grid(row=row+1, column=0, columnspan=3, pady=(8,0))
    fetch_btn = ttk.Button(btn_frm, text="Fetch", command=on_fetch)
    fetch_btn.grid(row=0, column=0, padx=(0,8))
    ttk.Button(btn_frm, text="Save Output As...", command=on_save_output).grid(row=0, column=1, padx=(0,8))
    ttk.Button(btn_frm, text="Clear", command=lambda: output.delete('1.0', tk.END)).grid(row=0, column=2, padx=(0,8))
    ttk.Button(btn_frm, text="Exit", command=root.destroy).grid(row=0, column=3)

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    frm.columnconfigure(1, weight=1)

    root.mainloop()


def main(argv=None):
    p = argparse.ArgumentParser(description="Login to mobile API and pull scouting data")
    p.add_argument("--url", required=False, help="Base URL of server (e.g. http://localhost:8080)")
    p.add_argument("--username", required=False)
    p.add_argument("--password", required=False)
    p.add_argument("--team", required=False, help="Optional team number to include in login request")
    p.add_argument("--endpoint", choices=list(ENDPOINTS.keys()), default="history", help="Which endpoint to call after login")
    p.add_argument("--limit", type=int, default=None, help="limit query param (where supported)")
    p.add_argument("--offset", type=int, default=None, help="offset query param (where supported)")
    p.add_argument("--insecure", action="store_true", help="Disable TLS/SSL cert verification (useful for local dev)")
    p.add_argument("--out", type=str, default=None, help="Save JSON response to this file")
    p.add_argument("--gui", action="store_true", help="Launch a simple Tkinter GUI")
    args = p.parse_args(argv)

    if args.gui:
        run_gui()
        return

    # CLI mode: require url, username, password
    if not args.url or not args.username or not args.password:
        p.print_help()
        print("\nEither use --gui or provide --url,--username,--password for CLI mode.")
        sys.exit(1)

    verify = not args.insecure

    try:
        print(f"Logging in to {args.url} as {args.username}...")
        token, login_resp = login(args.url, args.username, args.password, args.team, verify=verify)
        print("Login succeeded; token received (truncated): " + token[:32] + "...")

        endpoint = ENDPOINTS[args.endpoint]
        params = {}
        if args.limit is not None:
            params["limit"] = args.limit
        if args.offset is not None:
            params["offset"] = args.offset
        # some endpoints accept team_number or team_id filters; include when provided
        if args.team is not None and args.endpoint == "all":
            params["team_number"] = args.team

        print(f"Fetching data from {endpoint} with params={params} ...")
        resp = fetch_with_token(args.url, token, endpoint, params, verify=verify)

        # Pretty print or save
        out_json = json.dumps(resp, indent=2, ensure_ascii=False)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(out_json)
            print(f"Saved response to {args.out}")
        else:
            print(out_json)

    except requests.HTTPError as he:
        try:
            # try to show JSON error
            err = he.response.json()
        except Exception:
            err = he.response.text if he.response is not None else str(he)
        print("HTTP error:", err, file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print("Error:", str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
