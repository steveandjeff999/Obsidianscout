"""Simple Tkinter test UI for /api/mobile/scouting/all

This tool is a small developer helper to call the mobile API endpoint
`/api/mobile/scouting/all` and display results. It's intentionally
lightweight so you can run it from a dev machine while the server is
running locally.

Usage:
    & "<path-to-venv>\Scripts\python.exe" tools\tk_scouting_all_ui.py

Fields:
 - Server base URL (e.g. http://localhost:8080)
 - Bearer token (optional; required for protected endpoints)
 - Filters: team_number, event_id, match_id, limit, offset

This file is intended as a dev/test harness only.
"""
from __future__ import annotations

import threading
import json
import traceback
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

try:
    import requests
except Exception:
    requests = None


DEFAULT_BASE = "http://localhost:8080"


class ScoutingAllTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mobile API: /scouting/all Tester")
        self.geometry("800x600")

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        # Server / auth
        row = 0
        ttk.Label(frm, text="Server base URL:").grid(column=0, row=row, sticky=tk.W)
        self.base_entry = ttk.Entry(frm, width=60)
        self.base_entry.insert(0, DEFAULT_BASE)
        self.base_entry.grid(column=1, row=row, sticky=tk.W)

        # Login fields
        ttk.Label(frm, text="Username:").grid(column=0, row=row+1, sticky=tk.W)
        self.username_entry = ttk.Entry(frm, width=30)
        self.username_entry.grid(column=1, row=row+1, sticky=tk.W)

        ttk.Label(frm, text="Password:").grid(column=0, row=row+2, sticky=tk.W)
        self.password_entry = ttk.Entry(frm, width=30, show='*')
        self.password_entry.grid(column=1, row=row+2, sticky=tk.W)

        ttk.Label(frm, text="Login team_number (optional):").grid(column=0, row=row+3, sticky=tk.W)
        self.login_team_entry = ttk.Entry(frm, width=20)
        self.login_team_entry.grid(column=1, row=row+3, sticky=tk.W)

        ttk.Label(frm, text="Bearer token:").grid(column=0, row=row+4, sticky=tk.W)
        self.token_entry = ttk.Entry(frm, width=60)
        self.token_entry.grid(column=1, row=row+4, sticky=tk.W)

        # Filters
        ttk.Label(frm, text="Filter by scouted team# (optional):").grid(column=0, row=row+5, sticky=tk.W)
        self.team_entry = ttk.Entry(frm, width=20)
        self.team_entry.grid(column=1, row=row+5, sticky=tk.W)
        ttk.Label(frm, text="(Leave empty for all teams)", font=('TkDefaultFont', 8)).grid(column=1, row=row+5, sticky=tk.E, padx=(0, 5))

        ttk.Label(frm, text="event_id:").grid(column=0, row=row+6, sticky=tk.W)
        self.event_entry = ttk.Entry(frm, width=20)
        self.event_entry.grid(column=1, row=row+6, sticky=tk.W)

        ttk.Label(frm, text="match_id:").grid(column=0, row=row+7, sticky=tk.W)
        self.match_entry = ttk.Entry(frm, width=20)
        self.match_entry.grid(column=1, row=row+7, sticky=tk.W)

        ttk.Label(frm, text="limit:").grid(column=0, row=row+8, sticky=tk.W)
        self.limit_entry = ttk.Entry(frm, width=10)
        self.limit_entry.insert(0, "50")
        self.limit_entry.grid(column=1, row=row+8, sticky=tk.W)

        ttk.Label(frm, text="offset:").grid(column=0, row=row+9, sticky=tk.W)
        self.offset_entry = ttk.Entry(frm, width=10)
        self.offset_entry.insert(0, "0")
        self.offset_entry.grid(column=1, row=row+9, sticky=tk.W)

        # Buttons
        btn_frame = ttk.Frame(frm)
        btn_frame.grid(column=0, row=row+7, columnspan=2, pady=(8, 8))

        self.login_btn = ttk.Button(btn_frame, text="Login", command=self.on_login)
        self.login_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.fetch_btn = ttk.Button(btn_frame, text="Fetch /scouting/all", command=self.on_fetch)
        self.fetch_btn.pack(side=tk.LEFT)

        self.clear_btn = ttk.Button(btn_frame, text="Clear", command=self.on_clear)
        self.clear_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Results area
        self.results = scrolledtext.ScrolledText(frm, wrap=tk.WORD)
        self.results.grid(column=0, row=row+8, columnspan=2, sticky=(tk.N, tk.S, tk.E, tk.W))
        frm.rowconfigure(row+8, weight=1)
        frm.columnconfigure(1, weight=1)

    def on_clear(self):
        self.results.delete('1.0', tk.END)

    def on_fetch(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it in your venv: pip install requests")
            return

        # Disable button while running
        self.fetch_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.fetch_thread, daemon=True).start()

    def fetch_thread(self):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            token = self.token_entry.get().strip()
            params = {}
            if self.team_entry.get().strip():
                params['team_number'] = self.team_entry.get().strip()
            if self.event_entry.get().strip():
                params['event_id'] = self.event_entry.get().strip()
            if self.match_entry.get().strip():
                params['match_id'] = self.match_entry.get().strip()
            if self.limit_entry.get().strip():
                params['limit'] = self.limit_entry.get().strip()
            if self.offset_entry.get().strip():
                params['offset'] = self.offset_entry.get().strip()

            url = f"{base}/api/mobile/scouting/all"
            headers = {'Accept': 'application/json'}
            if token:
                headers['Authorization'] = f"Bearer {token}"

            self.append_text(f"GET {url}\nParams: {params}\nHeaders: {'Authorization: ***' if token else '(none)'}\n\n")
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            try:
                body = resp.json()
                pretty = json.dumps(body, indent=2, ensure_ascii=False)
            except Exception:
                pretty = resp.text

            self.append_text(f"Status: {resp.status_code}\n\n{pretty}\n")

        except Exception as e:
            self.append_text(f"Error: {str(e)}\n{traceback.format_exc()}\n")
        finally:
            self.fetch_btn.config(state=tk.NORMAL)

    def on_login(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it in your venv: pip install requests")
            return

        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        team_number = self.login_team_entry.get().strip()

        if not username or not password:
            messagebox.showwarning("Missing fields", "Please enter username and password to login")
            return

        # Disable login button while running
        self.login_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.login_thread, args=(username, password, team_number), daemon=True).start()

    def login_thread(self, username, password, team_number):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/auth/login"
            payload = {'username': username, 'password': password}
            if team_number:
                payload['team_number'] = team_number

            self.append_text(f"POST {url}\nPayload: {{'username': '***', 'team_number': '{team_number}'}}\n\n")
            resp = requests.post(url, json=payload, timeout=15)
            try:
                body = resp.json()
            except Exception:
                body = {'status_text': resp.text}

            self.append_text(f"Status: {resp.status_code}\n{json.dumps(body, indent=2, ensure_ascii=False)}\n")

            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                token = body.get('token')
                if token:
                    self.token_entry.delete(0, tk.END)
                    self.token_entry.insert(0, token)
                    messagebox.showinfo("Login successful", "Token stored in token field")
            else:
                messagebox.showerror("Login failed", f"Status {resp.status_code}: {body.get('error') if isinstance(body, dict) else str(body)}")

        except Exception as e:
            self.append_text(f"Login error: {str(e)}\n{traceback.format_exc()}\n")
        finally:
            self.login_btn.config(state=tk.NORMAL)

    def append_text(self, text: str):
        self.results.insert(tk.END, text)
        self.results.see(tk.END)


def main():
    app = ScoutingAllTester()
    app.mainloop()


if __name__ == '__main__':
    main()
