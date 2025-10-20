import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests
import json
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_BASE = os.environ.get('MOBILE_API_BASE', 'http://localhost:8080')
LOGIN_URL = f"{API_BASE}/api/mobile/auth/login"
CONFIG_URL = f"{API_BASE}/api/mobile/config/game"


class MobileConfigTinker(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Mobile GameConfig Tinker')
        self.geometry('900x600')

        # Login frame
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

        ttk.Button(lf, text='Login & Fetch Config', command=self.login_and_fetch).grid(row=0, column=6, padx=6)

        # Paned area
        paned = ttk.Panedwindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True, padx=8, pady=6)

        # Left: Tree
        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text='Form Structure').pack(anchor='w')
        self.tree = ttk.Treeview(left)
        self.tree.pack(fill='both', expand=True)

        # Right: JSON viewer
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        ttk.Label(right, text='Raw gameconfig.json').pack(anchor='w')
        self.json_text = scrolledtext.ScrolledText(right)
        self.json_text.pack(fill='both', expand=True)

        self.token = None

    def login_and_fetch(self):
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
        except Exception as e:
            messagebox.showerror('Request error', str(e))
            return

        # Fetch config
        headers = {'Authorization': f'Bearer {self.token}'}
        try:
            cfg = requests.get(CONFIG_URL, headers=headers, verify=False, timeout=10)
            if cfg.status_code != 200:
                messagebox.showerror('Fetch failed', f"Status: {cfg.status_code}\n{cfg.text}")
                return
            cfg_json = cfg.json().get('config')
            self.json_text.delete('1.0', tk.END)
            self.json_text.insert(tk.END, json.dumps(cfg_json, indent=2))
            self.render_tree(cfg_json)
        except Exception as e:
            messagebox.showerror('Request error', str(e))

    def render_tree(self, cfg_json):
        # Clear
        for i in self.tree.get_children():
            self.tree.delete(i)

        # If scouting_form exists, show sections/elements
        form = None
        if isinstance(cfg_json, dict):
            form = cfg_json.get('scouting_form') or cfg_json.get('form')

        if not form:
            self.tree.insert('', 'end', text='No scouting_form found')
            return

        for s_idx, section in enumerate(form.get('sections', [])):
            sec_id = self.tree.insert('', 'end', text=f"{section.get('name','Section')} [{s_idx}]")
            for e_idx, elem in enumerate(section.get('elements', [])):
                label = f"{elem.get('id','<no-id>')} ({elem.get('type','?')})"
                self.tree.insert(sec_id, 'end', text=label)


if __name__ == '__main__':
    app = MobileConfigTinker()
    app.mainloop()
