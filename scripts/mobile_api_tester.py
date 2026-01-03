"""Mobile API Tester (Tkinter)

Simple Tkinter GUI to:
 - Login to /api/mobile/auth/login (username, password, team_number)
 - Store the returned token in memory
 - Fetch matches: GET /api/mobile/matches?event_id=<event_id>

Usage:
    python scripts/mobile_api_tester.py

Dependencies:
    pip install requests

The UI fields:
 - Server Base URL (default: http://localhost:8080)
 - Username
 - Password
 - Team Number
 - Event ID (default: 1)

Buttons:
 - Login
 - Fetch Matches
 - Copy Token
 - Logout

"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import urllib3
import json
from datetime import datetime

# Disable insecure request warnings when SSL verification is disabled in the UI
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REQUEST_TIMEOUT = 8  # seconds

class MobileAPITester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mobile API Tester")
        self.geometry("800x600")

        self.token = None
        self.login_response = None

        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # Server and auth frame
        top = ttk.LabelFrame(frm, text="Server & Authentication", padding=8)
        top.pack(fill=tk.X, pady=4)

        ttk.Label(top, text="Base URL:").grid(row=0, column=0, sticky=tk.W)
        self.base_entry = ttk.Entry(top, width=56)
        self.base_entry.grid(row=0, column=1, sticky=tk.W, padx=4)
        self.base_entry.insert(0, "http://localhost:8080")

        ttk.Label(top, text="Username:").grid(row=1, column=0, sticky=tk.W)
        self.username_entry = ttk.Entry(top, width=24)
        self.username_entry.grid(row=1, column=1, sticky=tk.W, padx=4)

        ttk.Label(top, text="Password:").grid(row=1, column=2, sticky=tk.W)
        self.password_entry = ttk.Entry(top, width=24, show="*")
        self.password_entry.grid(row=1, column=3, sticky=tk.W, padx=4)

        ttk.Label(top, text="Team #: ").grid(row=2, column=0, sticky=tk.W)
        self.team_entry = ttk.Entry(top, width=12)
        self.team_entry.grid(row=2, column=1, sticky=tk.W, padx=4)

        ttk.Label(top, text="Event ID:").grid(row=2, column=2, sticky=tk.W)
        self.event_entry = ttk.Entry(top, width=12)
        self.event_entry.grid(row=2, column=3, sticky=tk.W, padx=4)
        self.event_entry.insert(0, "1")

        # SSL verification toggle: default to disabled to allow self-signed certs
        self.disable_ssl_var = tk.BooleanVar(value=True)
        self.ssl_check = ttk.Checkbutton(top, text="Disable SSL verification (allow self-signed certs)", variable=self.disable_ssl_var)
        self.ssl_check.grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(6,0))

        # Buttons
        btn_frame = ttk.Frame(top)
        btn_frame.grid(row=4, column=0, columnspan=4, pady=(8,0), sticky=tk.W)

        self.login_btn = ttk.Button(btn_frame, text="Login", command=self.login)
        self.login_btn.grid(row=0, column=0, padx=4)

        self.logout_btn = ttk.Button(btn_frame, text="Logout", command=self.logout, state=tk.DISABLED)
        self.logout_btn.grid(row=0, column=1, padx=4)

        self.copy_btn = ttk.Button(btn_frame, text="Copy Token", command=self.copy_token, state=tk.DISABLED)
        self.copy_btn.grid(row=0, column=2, padx=4)

        self.fetch_btn = ttk.Button(btn_frame, text="Fetch Matches", command=self.fetch_matches, state=tk.DISABLED)
        self.fetch_btn.grid(row=0, column=3, padx=4)

        # New: Fetch Events
        self.fetch_events_btn = ttk.Button(btn_frame, text="Fetch Events", command=self.fetch_events, state=tk.DISABLED)
        self.fetch_events_btn.grid(row=0, column=4, padx=4)

        # Response display
        resp_frame = ttk.LabelFrame(frm, text="Response / Output", padding=8)
        resp_frame.pack(fill=tk.BOTH, expand=True, pady=6)

        self.status_label = ttk.Label(resp_frame, text="Not logged in")
        self.status_label.pack(anchor=tk.W)

        self.text = scrolledtext.ScrolledText(resp_frame, wrap=tk.WORD)
        self.text.pack(fill=tk.BOTH, expand=True)

        # Footer
        footer = ttk.Frame(frm)
        footer.pack(fill=tk.X)
        ttk.Label(footer, text="Tip: use your server base URL (e.g., http://localhost:8080) and include trailing port if needed.").pack(anchor=tk.W)

    def _set_status(self, text):
        self.status_label.config(text=text)

    def _append_text(self, text):
        self.text.insert(tk.END, text + "\n")
        self.text.see(tk.END)

    def login(self):
        base = self.base_entry.get().strip().rstrip('/')
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        team = self.team_entry.get().strip()

        if not (base and username and password and team):
            messagebox.showwarning("Missing data", "Please provide Base URL, username, password and team number.")
            return

        url = f"{base}/api/mobile/auth/login"
        payload = {"username": username, "password": password, "team_number": int(team)}

        try:
            self._set_status("Logging in...")
            r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT, verify=not self.disable_ssl_var.get())
        except Exception as e:
            messagebox.showerror("Request failed", str(e))
            self._set_status("Login failed")
            return

        try:
            data = r.json()
        except Exception:
            messagebox.showerror("Invalid response", f"Non-JSON response (status {r.status_code})")
            self._append_text(r.text)
            self._set_status("Login failed")
            return

        if r.status_code == 200 and data.get('success'):
            self.token = data.get('token')
            self.login_response = data
            self._set_status(f"Logged in as {data['user']['username']} (team {data['user'].get('team_number')})")
            self._append_text("Login successful:\n" + json.dumps(data, indent=2))
            self.logout_btn.config(state=tk.NORMAL)
            self.copy_btn.config(state=tk.NORMAL)
            self.fetch_btn.config(state=tk.NORMAL)
            self.fetch_events_btn.config(state=tk.NORMAL)
        else:
            err = data.get('error') or data.get('message') or 'Login failed'
            messagebox.showerror("Login failed", f"{err} (status {r.status_code})")
            self._append_text("Login failed response:\n" + json.dumps(data, indent=2))
            self._set_status("Login failed")

    def logout(self):
        self.token = None
        self.login_response = None
        self._set_status("Logged out")
        self._append_text("Logged out")
        self.logout_btn.config(state=tk.DISABLED)
        self.copy_btn.config(state=tk.DISABLED)
        self.fetch_btn.config(state=tk.DISABLED)
        self.fetch_events_btn.config(state=tk.DISABLED)

    def copy_token(self):
        if not self.token:
            return
        self.clipboard_clear()
        self.clipboard_append(self.token)
        self._append_text("Token copied to clipboard")

    def fetch_matches(self):
        if not self.token:
            messagebox.showwarning("Not authenticated", "Please login first")
            return

        base = self.base_entry.get().strip().rstrip('/')
        event_id = self.event_entry.get().strip() or '1'

        url = f"{base}/api/mobile/matches"
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"event_id": event_id}

        try:
            self._set_status("Fetching matches...")
            r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT, verify=not self.disable_ssl_var.get())
        except Exception as e:
            messagebox.showerror("Request failed", str(e))
            self._set_status("Fetch failed")
            return

        try:
            data = r.json()
        except Exception:
            messagebox.showerror("Invalid response", f"Non-JSON response (status {r.status_code})")
            self._append_text(r.text)
            self._set_status("Fetch failed")
            return

        if r.status_code == 200 and data.get('success'):
            pretty = json.dumps(data, indent=2)
            self._append_text("Matches response:\n" + pretty)
            self._set_status(f"Fetched {len(data.get('matches', []))} matches")
        else:
            err = data.get('error') or data.get('message') or f"HTTP {r.status_code}"
            messagebox.showerror("Fetch failed", f"{err} (status {r.status_code})")
            self._append_text("Fetch failed response:\n" + json.dumps(data, indent=2))
            self._set_status("Fetch failed")

    def fetch_events(self):
        if not self.token:
            messagebox.showwarning("Not authenticated", "Please login first")
            return

        base = self.base_entry.get().strip().rstrip('/')
        url = f"{base}/api/mobile/events"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            self._set_status("Fetching events...")
            r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, verify=not self.disable_ssl_var.get())
        except Exception as e:
            messagebox.showerror("Request failed", str(e))
            self._set_status("Fetch failed")
            return

        try:
            data = r.json()
        except Exception:
            messagebox.showerror("Invalid response", f"Non-JSON response (status {r.status_code})")
            self._append_text(r.text)
            self._set_status("Fetch failed")
            return

        if r.status_code == 200 and data.get('success'):
            pretty = json.dumps(data, indent=2)
            self._append_text("Events response:\n" + pretty)
            self._set_status(f"Fetched {len(data.get('events', []))} events")
        else:
            err = data.get('error') or data.get('message') or f"HTTP {r.status_code}"
            messagebox.showerror("Fetch failed", f"{err} (status {r.status_code})")
            self._append_text("Fetch failed response:\n" + json.dumps(data, indent=2))
            self._set_status("Fetch failed")

if __name__ == '__main__':
    app = MobileAPITester()
    app.mainloop()
