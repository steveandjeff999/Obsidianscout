import tkinter as tk
from tkinter import ttk, scrolledtext, simpledialog
import requests
import json

# Simple Tkinter UI to login and fetch teams from the mobile API
# Usage: python tools/tk_fetch_teams_ui.py

BASE_URL = 'https://localhost:8080'

class TeamsFetcherApp:
    def __init__(self, root):
        self.root = root
        root.title('Fetch Teams (Mobile API)')

        frm = ttk.Frame(root, padding=10)
        frm.grid()

        ttk.Label(frm, text='Server Base URL:').grid(column=0, row=0, sticky='w')
        self.base_url_var = tk.StringVar(value=BASE_URL)
        ttk.Entry(frm, textvariable=self.base_url_var, width=50).grid(column=1, row=0, columnspan=2)

        ttk.Label(frm, text='Username:').grid(column=0, row=1, sticky='w')
        self.username = tk.StringVar()
        ttk.Entry(frm, textvariable=self.username).grid(column=1, row=1, sticky='w')

        ttk.Label(frm, text='Password:').grid(column=0, row=2, sticky='w')
        self.password = tk.StringVar()
        ttk.Entry(frm, textvariable=self.password, show='*').grid(column=1, row=2, sticky='w')

        ttk.Button(frm, text='Login', command=self.login).grid(column=2, row=1, rowspan=2, sticky='ns')

        ttk.Label(frm, text='Or paste token:').grid(column=0, row=3, sticky='w')
        self.token_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.token_var, width=50).grid(column=1, row=3, columnspan=2, sticky='w')

        ttk.Label(frm, text='Event ID or Code:').grid(column=0, row=4, sticky='w')
        self.event_input = tk.StringVar()
        ttk.Entry(frm, textvariable=self.event_input).grid(column=1, row=4, sticky='w')

        ttk.Button(frm, text='Resolve & Fetch Teams', command=self.fetch_teams).grid(column=2, row=4, sticky='w')

        self.result_box = scrolledtext.ScrolledText(frm, width=100, height=30)
        self.result_box.grid(column=0, row=5, columnspan=3, pady=10)

        ttk.Button(frm, text='Quit', command=root.quit).grid(column=2, row=6, sticky='e')

    def login(self):
        url = self.base_url_var.get().rstrip('/') + '/api/mobile/auth/login'
        payload = {
            'username': self.username.get(),
            'password': self.password.get()
        }
        try:
            resp = requests.post(url, json=payload, verify=False)
            data = resp.json()
            if data.get('success') and data.get('token'):
                self.token_var.set(data['token'])
                self.result_box.insert(tk.END, 'Login successful. Token set.\n')
            else:
                self.result_box.insert(tk.END, f'Login failed: {data}\n')
        except Exception as e:
            self.result_box.insert(tk.END, f'Login error: {e}\n')

    def resolve_event_code(self, token, query):
        # If query is numeric, treat as event_id
        try:
            event_id = int(query)
            return event_id
        except Exception:
            # fetch events and find by code (or name)
            url = self.base_url_var.get().rstrip('/') + '/api/mobile/events'
            headers = {'Authorization': f'Bearer {token}'}
            try:
                resp = requests.get(url, headers=headers, verify=False)
                events = resp.json().get('events', [])
                for ev in events:
                    if ev.get('code') == query or ev.get('name') == query:
                        return ev.get('id')
            except Exception as e:
                self.result_box.insert(tk.END, f'Error resolving event code: {e}\n')
        return None

    def fetch_teams(self):
        token = self.token_var.get().strip()
        if not token:
            self.result_box.insert(tk.END, 'No token available. Please login or paste a token.\n')
            return

        query = self.event_input.get().strip()
        params = {}
        if query:
            event_id = self.resolve_event_code(token, query)
            if event_id is None:
                self.result_box.insert(tk.END, f'Could not resolve event "{query}".\n')
                return
            params['event_id'] = event_id

        url = self.base_url_var.get().rstrip('/') + '/api/mobile/teams'
        headers = {'Authorization': f'Bearer {token}'}
        try:
            resp = requests.get(url, headers=headers, params=params, verify=False)
            try:
                data = resp.json()
            except Exception:
                self.result_box.insert(tk.END, f'Non-JSON response: {resp.text}\n')
                return

            pretty = json.dumps(data, indent=2)
            self.result_box.insert(tk.END, pretty + '\n')
        except Exception as e:
            self.result_box.insert(tk.END, f'Fetch error: {e}\n')


if __name__ == '__main__':
    root = tk.Tk()
    app = TeamsFetcherApp(root)
    root.mainloop()
