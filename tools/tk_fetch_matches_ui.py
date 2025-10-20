import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import simpledialog
import requests
import json
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = os.environ.get('MOBILE_API_BASE', 'http://127.0.0.1:8080/')
LOGIN_URL = f"{API_BASE}/api/mobile/auth/login"
MATCHES_URL = f"{API_BASE}/api/mobile/matches"


class FetchMatchesUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Fetch Matches UI')
        self.geometry('1000x650')

        lf = ttk.LabelFrame(self, text='Login')
        lf.pack(fill='x', padx=8, pady=6)

        ttk.Label(lf, text='Username (optional)').grid(row=0, column=0, sticky='w')
        self.username_var = tk.StringVar()
        ttk.Entry(lf, textvariable=self.username_var, width=30).grid(row=0, column=1)

        ttk.Label(lf, text='Team Number').grid(row=0, column=2, sticky='w')
        self.team_var = tk.StringVar(value='5454')
        ttk.Entry(lf, textvariable=self.team_var, width=10).grid(row=0, column=3)

        ttk.Label(lf, text='Password').grid(row=0, column=4, sticky='w')
        self.password_var = tk.StringVar(value='5454')
        ttk.Entry(lf, textvariable=self.password_var, show='*', width=15).grid(row=0, column=5)

        ttk.Button(lf, text='Login', command=self.login).grid(row=0, column=6, padx=6)
        ttk.Button(lf, text='Use Token', command=self.prompt_token).grid(row=0, column=7, padx=6)

        # Event selection
        ef = ttk.Frame(self)
        ef.pack(fill='x', padx=8)
        ttk.Label(ef, text='Event ID').pack(side='left')
        self.event_var = tk.StringVar()
        ttk.Entry(ef, textvariable=self.event_var, width=10).pack(side='left', padx=6)
        ttk.Button(ef, text='Fetch Matches', command=self.fetch_matches).pack(side='left', padx=6)

        # Paned area
        paned = ttk.Panedwindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=8, pady=6)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text='Matches Tree').pack(anchor='w')
        self.tree = ttk.Treeview(left)
        self.tree.pack(fill='both', expand=True)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        ttk.Label(right, text='Raw Matches JSON').pack(anchor='w')
        self.json_text = scrolledtext.ScrolledText(right)
        self.json_text.pack(fill='both', expand=True)

        self.token = None

    def prompt_token(self):
        tok = simpledialog.askstring('Token', 'Paste Bearer token here (no "Bearer ")')
        if tok:
            self.token = tok
            messagebox.showinfo('Token set', 'Token stored in memory for this session')

    def login(self):
        username = self.username_var.get().strip() or None
        team = self.team_var.get().strip()
        password = self.password_var.get().strip()

        payload = {'password': password}
        if username:
            payload['username'] = username
            payload['team_number'] = int(team) if team else None
        else:
            payload['team_number'] = int(team) if team else None

        try:
            resp = requests.post(LOGIN_URL, json=payload, verify=False, timeout=10)
            if resp.status_code != 200:
                messagebox.showerror('Login failed', f"Status: {resp.status_code}\n{resp.text}")
                return
            data = resp.json()
            if not data.get('success'):
                messagebox.showerror('Login failed', str(data))
                return
            self.token = data.get('token')
            messagebox.showinfo('Login successful', 'Token acquired')
        except Exception as e:
            messagebox.showerror('Request error', str(e))

    def fetch_matches(self):
        event_id = self.event_var.get().strip()
        if not event_id:
            messagebox.showerror('Missing', 'Please enter event_id')
            return
        # Accept either numeric event_id or event code (e.g. 'arsea').
        try:
            params = {'event_id': int(event_id)}
        except ValueError:
            # Try to resolve event code to id via /events (requires token)
            resolved = self.resolve_event_code(event_id)
            if resolved is None:
                messagebox.showerror('Invalid event', f"Could not resolve event code or id: {event_id}")
                return
            params = {'event_id': resolved}
        headers = {'Authorization': f'Bearer {self.token}'} if self.token else {}

        try:
            resp = requests.get(MATCHES_URL, params=params, headers=headers, verify=False, timeout=15)
            if resp.status_code != 200:
                messagebox.showerror('Fetch failed', f"Status: {resp.status_code}\n{resp.text}")
                return
            j = resp.json()
            self.json_text.delete('1.0', tk.END)
            self.json_text.insert(tk.END, json.dumps(j, indent=2))
            self.render_tree(j)
        except Exception as e:
            messagebox.showerror('Request error', str(e))

    def render_tree(self, j):
        for i in self.tree.get_children():
            self.tree.delete(i)
        if not isinstance(j, dict) or 'matches' not in j:
            self.tree.insert('', 'end', text='No matches')
            return
        for m in j.get('matches', []):
            node = self.tree.insert('', 'end', text=f"Match {m.get('match_number')} (id:{m.get('id')})")
            self.tree.insert(node, 'end', text=f"Type: {m.get('match_type')}")
            self.tree.insert(node, 'end', text=f"Red: {m.get('red_alliance')}")
            self.tree.insert(node, 'end', text=f"Blue: {m.get('blue_alliance')}")
            self.tree.insert(node, 'end', text=f"Score: {m.get('red_score')} - {m.get('blue_score')}")

    def resolve_event_code(self, code_or_name):
        """Resolve an event code or name to a numeric event id by calling /api/mobile/events.

        Returns event id (int) or None if not found or token missing.
        """
        if not self.token:
            messagebox.showerror('Not authenticated', 'Please login or provide a token before resolving event codes.')
            return None

        headers = {'Authorization': f'Bearer {self.token}'}
        try:
            resp = requests.get(f"{API_BASE}/api/mobile/events", headers=headers, verify=False, timeout=10)
            if resp.status_code != 200:
                # Could not fetch events
                return None
            data = resp.json()
            events = data.get('events', [])
            target = code_or_name.strip().lower()
            for ev in events:
                code = (ev.get('code') or '').lower()
                name = (ev.get('name') or '').lower()
                if code == target or name == target:
                    return ev.get('id')
            return None
        except Exception:
            return None


if __name__ == '__main__':
    app = FetchMatchesUI()
    app.mainloop()
