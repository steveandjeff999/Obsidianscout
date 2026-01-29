import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import simpledialog
import requests
import json
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = os.environ.get('MOBILE_API_BASE', 'https://127.0.0.1:8080')
LOGIN_URL = f"{API_BASE.rstrip('/')}/api/mobile/auth/login"
EVENTS_URL = f"{API_BASE.rstrip('/')}/api/mobile/events"


class FetchEventsUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Fetch Events (My Team)')
        self.geometry('900x650')

        lf = ttk.LabelFrame(self, text='Login')
        lf.pack(fill='x', padx=8, pady=6)

        ttk.Label(lf, text='Username (optional)').grid(row=0, column=0, sticky='w')
        self.username_var = tk.StringVar()
        ttk.Entry(lf, textvariable=self.username_var, width=30).grid(row=0, column=1)

        ttk.Label(lf, text='Team Number').grid(row=0, column=2, sticky='w')
        self.team_var = tk.StringVar()
        ttk.Entry(lf, textvariable=self.team_var, width=10).grid(row=0, column=3)

        ttk.Label(lf, text='Password').grid(row=0, column=4, sticky='w')
        self.password_var = tk.StringVar()
        ttk.Entry(lf, textvariable=self.password_var, show='*', width=15).grid(row=0, column=5)

        ttk.Button(lf, text='Login', command=self.login).grid(row=0, column=6, padx=6)
        ttk.Button(lf, text='Use Token', command=self.prompt_token).grid(row=0, column=7, padx=6)

        # API base and insecure option
        ttk.Label(lf, text='API Base').grid(row=1, column=0, sticky='w')
        self.api_base_var = tk.StringVar(value=API_BASE)
        ttk.Entry(lf, textvariable=self.api_base_var, width=60).grid(row=1, column=1, columnspan=4, sticky='w')
        self.allow_insecure_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf, text='Allow insecure HTTPS (skip cert verify)', variable=self.allow_insecure_var).grid(row=1, column=6, columnspan=2, sticky='w')

        # Controls
        cf = ttk.Frame(self)
        cf.pack(fill='x', padx=8, pady=(0,6))
        ttk.Button(cf, text='Fetch Events for My Team', command=self.fetch_events).pack(side='left')
        ttk.Button(cf, text='Clear', command=self.clear).pack(side='left', padx=6)

        # Paned area
        paned = ttk.Panedwindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=8, pady=6)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text='Events Tree').pack(anchor='w')
        self.tree = ttk.Treeview(left)
        self.tree.pack(fill='both', expand=True)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        ttk.Label(right, text='Raw Events JSON').pack(anchor='w')
        self.json_text = scrolledtext.ScrolledText(right)
        self.json_text.pack(fill='both', expand=True)

        self.token = None

    def prompt_token(self):
        tok = simpledialog.askstring('Token', 'Paste Bearer token here (no "Bearer ")')
        if tok:
            self.token = tok.strip()
            messagebox.showinfo('Token set', 'Token stored in memory for this session')

    def login(self):
        username = self.username_var.get().strip() or None
        team = self.team_var.get().strip()
        password = self.password_var.get().strip()

        if not password and not team:
            messagebox.showerror('Missing', 'Please provide at least a team number and password')
            return

        payload = {'password': password}
        # Support alphanumeric team numbers for offseason (e.g., '581B')
        if team:
            try:
                team_number = int(team)
            except ValueError:
                team_number = team.upper()
        else:
            team_number = None

        if username:
            payload['username'] = username
            payload['team_number'] = team_number
        else:
            payload['team_number'] = team_number

        try:
            base = self.api_base_var.get().rstrip('/')
            login_url = f"{base}/api/mobile/auth/login"
            verify = not bool(self.allow_insecure_var.get())
            resp = requests.post(login_url, json=payload, verify=verify, timeout=10)
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

    def fetch_events(self):
        headers = {'Authorization': f'Bearer {self.token}'} if self.token else {}
        try:
            base = self.api_base_var.get().rstrip('/')
            events_url = f"{base}/api/mobile/events"
            verify = not bool(self.allow_insecure_var.get())
            resp = requests.get(events_url, headers=headers, verify=verify, timeout=15)
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
        if not isinstance(j, dict) or 'events' not in j:
            self.tree.insert('', 'end', text='No events')
            return
        for ev in j.get('events', []):
            code = ev.get('code') or ''
            node = self.tree.insert('', 'end', text=f"{ev.get('name')} ({ev.get('id')}) - {code}")
            self.tree.insert(node, 'end', text=f"Location: {ev.get('location')}")
            self.tree.insert(node, 'end', text=f"Dates: {ev.get('start_date')} - {ev.get('end_date')}")
            self.tree.insert(node, 'end', text=f"Team count: {ev.get('team_count')}")

    def clear(self):
        self.json_text.delete('1.0', tk.END)
        for i in self.tree.get_children():
            self.tree.delete(i)


if __name__ == '__main__':
    app = FetchEventsUI()
    app.mainloop()
