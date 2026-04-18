#!/usr/bin/env python3
"""
Test script for EPA/OPR history mobile API endpoint
Provides a Tkinter UI to login, select an event, and fetch per-match EPA and OPR data
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import requests
import urllib3
import json
from datetime import datetime
import threading

class EPAOPRHistoryTester:
    def __init__(self, root):
        self.root = root
        self.root.title("EPA/OPR History API Tester")
        self.root.geometry("1200x800")
        
        self.api_base = "http://localhost:5000/api/mobile"
        self.token = None
        self.user_info = None
        self.events = []
        self.verify_ssl_var = tk.BooleanVar(value=True)
        self.request_timeout_var = tk.StringVar(value="180")
        
        self.setup_ui()
    
    def setup_ui(self):
        """Initialize the UI with tabs for different stages"""
        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Tab 1: Login
        self.login_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.login_frame, text="1. Login")
        self.setup_login_tab()
        
        # Tab 2: Event Selection
        self.event_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.event_frame, text="2. Select Event")
        self.setup_event_tab()
        
        # Tab 3: Fetch Data
        self.fetch_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.fetch_frame, text="3. Fetch EPA/OPR")
        self.setup_fetch_tab()
        
        # Tab 4: Results
        self.results_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.results_frame, text="4. Results")
        self.setup_results_tab()
    
    def setup_login_tab(self):
        """Setup login tab"""
        frame = ttk.LabelFrame(self.login_frame, text="API Connection & Login", padding=20)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # API Base URL
        ttk.Label(frame, text="API Base URL:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.api_url_entry = ttk.Entry(frame, width=50)
        self.api_url_entry.insert(0, self.api_base)
        self.api_url_entry.grid(row=0, column=1, sticky=tk.EW, pady=5)
        
        # Username
        ttk.Label(frame, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.username_entry = ttk.Entry(frame, width=50)
        self.username_entry.grid(row=1, column=1, sticky=tk.EW, pady=5)
        
        # Password
        ttk.Label(frame, text="Password:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.password_entry = ttk.Entry(frame, width=50, show="*")
        self.password_entry.grid(row=2, column=1, sticky=tk.EW, pady=5)
        
        # Team Number
        ttk.Label(frame, text="Team Number:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.team_entry = ttk.Entry(frame, width=50)
        self.team_entry.grid(row=3, column=1, sticky=tk.EW, pady=5)

        # SSL verification toggle
        self.verify_ssl_check = ttk.Checkbutton(
            frame,
            text="Verify SSL certificates (uncheck to allow insecure HTTPS)",
            variable=self.verify_ssl_var
        )
        self.verify_ssl_check.grid(row=4, column=1, sticky=tk.W, pady=5)
        
        # Login Button
        ttk.Button(frame, text="Login", command=self.do_login).grid(row=5, column=1, sticky=tk.E, pady=20)
        
        # Status
        ttk.Label(frame, text="Status:").grid(row=6, column=0, sticky=tk.W, pady=5)
        self.login_status = ttk.Label(frame, text="Not logged in", foreground="red")
        self.login_status.grid(row=6, column=1, sticky=tk.W, pady=5)
        
        frame.columnconfigure(1, weight=1)

    def _request_kwargs(self, connect_timeout):
        """Build requests kwargs with optional insecure HTTPS support.

        Use an infinite read timeout so large responses can complete as long as
        the connection remains active.
        """
        verify_ssl = bool(self.verify_ssl_var.get())
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return {
            # requests timeout tuple = (connect timeout, read timeout)
            # read timeout None => do not time out while data is still flowing
            "timeout": (connect_timeout, None),
            "verify": verify_ssl,
        }

    def _get_timeout_seconds(self):
        """Read timeout from UI with sane fallback and bounds."""
        try:
            value = int((self.request_timeout_var.get() or "").strip())
        except Exception:
            value = 180
        return max(10, min(value, 1200))
    
    def setup_event_tab(self):
        """Setup event selection tab"""
        frame = ttk.LabelFrame(self.event_frame, text="Select Event", padding=20)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(frame, text="Event ID (numeric, code, or year-prefixed):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.event_id_entry = ttk.Entry(frame, width=50)
        self.event_id_entry.grid(row=0, column=1, sticky=tk.EW, pady=5)
        
        # Or select from recent events
        ttk.Label(frame, text="Or paste event code (e.g., OKTU or 2026OKTU):").grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=10)
        
        # Team numbers to fetch
        ttk.Label(frame, text="Team Numbers (comma-separated, leave empty for all):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.team_numbers_entry = ttk.Entry(frame, width=50)
        self.team_numbers_entry.grid(row=2, column=1, sticky=tk.EW, pady=5)
        
        # Match limit
        ttk.Label(frame, text="Max Matches per Team:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.limit_entry = ttk.Entry(frame, width=50)
        self.limit_entry.insert(0, "200")
        self.limit_entry.grid(row=3, column=1, sticky=tk.EW, pady=5)
        
        frame.columnconfigure(1, weight=1)
    
    def setup_fetch_tab(self):
        """Setup fetch tab"""
        frame = ttk.LabelFrame(self.fetch_frame, text="Fetch Options", padding=20)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        timeout_row = ttk.Frame(frame)
        timeout_row.pack(fill=tk.X, pady=5)
        ttk.Label(timeout_row, text="Connect Timeout (seconds):").pack(side=tk.LEFT)
        self.timeout_entry = ttk.Entry(timeout_row, width=10, textvariable=self.request_timeout_var)
        self.timeout_entry.pack(side=tk.LEFT, padx=(8, 0))
        
        ttk.Button(frame, text="Fetch EPA/OPR History", command=self.do_fetch).pack(pady=10)
        
        # Progress
        self.fetch_status = ttk.Label(frame, text="Ready", foreground="blue")
        self.fetch_status.pack(pady=5)
        
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=10)
    
    def setup_results_tab(self):
        """Setup results tab"""
        frame = ttk.LabelFrame(self.results_frame, text="Results", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create treeview for team data
        columns = ('Team', 'Name', 'OPR', 'DPR', 'CCWM', 'Matches')
        self.tree = ttk.Treeview(frame, columns=columns, height=15)
        self.tree.column('#0', width=0, stretch=tk.NO)
        self.tree.column('Team', anchor=tk.W, width=80)
        self.tree.column('Name', anchor=tk.W, width=200)
        self.tree.column('OPR', anchor=tk.CENTER, width=100)
        self.tree.column('DPR', anchor=tk.CENTER, width=100)
        self.tree.column('CCWM', anchor=tk.CENTER, width=100)
        self.tree.column('Matches', anchor=tk.CENTER, width=80)
        
        self.tree.heading('#0', text='', anchor=tk.W)
        self.tree.heading('Team', text='Team #', anchor=tk.W)
        self.tree.heading('Name', text='Team Name', anchor=tk.W)
        self.tree.heading('OPR', text='OPR', anchor=tk.CENTER)
        self.tree.heading('DPR', text='DPR', anchor=tk.CENTER)
        self.tree.heading('CCWM', text='CCWM', anchor=tk.CENTER)
        self.tree.heading('Matches', text='# Matches', anchor=tk.CENTER)
        
        # Scrollbars
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        
        # Bind click to show match details
        self.tree.bind('<Double-1>', self.on_team_click)
        
        # Status/Detail text
        detail_frame = ttk.LabelFrame(self.results_frame, text="Match Details (Double-click team)", padding=10)
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.detail_text = scrolledtext.ScrolledText(detail_frame, height=10, width=100)
        self.detail_text.pack(fill=tk.BOTH, expand=True)
    
    def do_login(self):
        """Perform login"""
        self.api_base = self.api_url_entry.get()
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        team_number = self.team_entry.get().strip()
        
        if not all([username, password, team_number]):
            messagebox.showerror("Input Error", "All fields are required")
            return
        
        self.login_status.config(text="Logging in...", foreground="blue")
        self.root.update()
        
        try:
            response = requests.post(
                f"{self.api_base}/auth/login",
                json={
                    "username": username,
                    "password": password,
                    "team_number": team_number
                },
                **self._request_kwargs(connect_timeout=self._get_timeout_seconds())
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    self.token = data['token']
                    self.user_info = data['user']
                    self.login_status.config(
                        text=f"✓ Logged in as {self.user_info['username']} (Team {self.user_info['team_number']})",
                        foreground="green"
                    )
                    messagebox.showinfo("Login Success", f"Logged in as {username}")
                    self.notebook.select(1)  # Move to event tab
                else:
                    messagebox.showerror("Login Failed", data.get('error', 'Unknown error'))
                    self.login_status.config(text="Login failed", foreground="red")
            else:
                messagebox.showerror("Login Error", f"Server returned {response.status_code}")
                self.login_status.config(text=f"Error: {response.status_code}", foreground="red")

        except requests.exceptions.Timeout:
            messagebox.showerror("Timeout", "Login connect timed out. Increase Connect Timeout (seconds) on the Fetch tab and try again.")
            self.login_status.config(text="Login timed out", foreground="red")
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.login_status.config(text=f"Error: {str(e)}", foreground="red")
    
    def do_fetch(self):
        """Fetch EPA/OPR history"""
        if not self.token:
            messagebox.showerror("Not Logged In", "Please login first")
            return
        
        event_id = self.event_id_entry.get().strip()
        if not event_id:
            messagebox.showerror("Missing Event", "Please enter an event ID or code")
            return
        
        team_numbers = self.team_numbers_entry.get().strip()
        try:
            limit = int(self.limit_entry.get())
        except ValueError:
            limit = 200
        
        # Run fetch in background thread
        self.progress.start()
        self.fetch_status.config(text="Fetching...", foreground="blue")
        self.root.update()
        
        thread = threading.Thread(
            target=self._fetch_background,
            args=(event_id, team_numbers, limit, self._get_timeout_seconds())
        )
        thread.daemon = True
        thread.start()
    
    def _fetch_background(self, event_id, team_numbers, limit, timeout_seconds):
        """Background thread for fetching"""
        try:
            payload = {
                "event_id": event_id,
                "limit": limit
            }
            
            if team_numbers:
                # Parse comma-separated team numbers
                payload["team_numbers"] = [int(t.strip()) for t in team_numbers.split(',')]
            
            response = requests.post(
                f"{self.api_base}/config/game/stats/epa-opr-history",
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                **self._request_kwargs(connect_timeout=timeout_seconds)
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    self.root.after(0, lambda: self._display_results(data))
                    self.root.after(0, lambda: self._update_status(f"✓ Fetched {data['team_count']} teams", "green"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("Fetch Error", data.get('error', 'Unknown error')))
                    self.root.after(0, lambda: self._update_status(f"Error: {data.get('error')}", "red"))
            else:
                error_msg = f"Server returned {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except:
                    pass
                self.root.after(0, lambda: messagebox.showerror("Fetch Error", error_msg))
                self.root.after(0, lambda: self._update_status(f"Error: {error_msg}", "red"))

        except requests.exceptions.Timeout:
            msg = f"Request timed out after {timeout_seconds}s. Try a larger timeout, fewer teams, or a smaller match limit."
            self.root.after(0, lambda: messagebox.showerror("Timeout", msg))
            self.root.after(0, lambda: self._update_status("Timed out", "red"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))
            self.root.after(0, lambda: self._update_status(f"Error: {str(e)}", "red"))
        
        finally:
            self.root.after(0, self.progress.stop)
    
    def _update_status(self, text, color):
        """Update fetch status"""
        self.fetch_status.config(text=text, foreground=color)
    
    def _display_results(self, data):
        """Display results in treeview"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Store raw data for detail display
        self.raw_data = data
        
        # Add team data
        for team_data in data.get('teams', []):
            team_num = team_data['team_number']
            team_name = team_data['team_name']
            opr_data = team_data.get('opr_data') or {}
            epa_history = team_data.get('match_epa_history') or []
            
            opr = opr_data.get('opr')
            dpr = opr_data.get('dpr')
            ccwm = opr_data.get('ccwm')
            
            opr_str = f"{opr:.1f}" if opr is not None else "N/A"
            dpr_str = f"{dpr:.1f}" if dpr is not None else "N/A"
            ccwm_str = f"{ccwm:.1f}" if ccwm is not None else "N/A"
            match_count = len(epa_history)
            
            self.tree.insert(
                '',
                'end',
                iid=f"team_{team_num}",
                values=(team_num, team_name, opr_str, dpr_str, ccwm_str, match_count)
            )
        
        self.notebook.select(3)  # Move to results tab
    
    def on_team_click(self, event):
        """Show match details when team is clicked"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item_id = selection[0]
        team_num = int(item_id.replace('team_', ''))
        
        # Find team data
        team_data = None
        for t in self.raw_data.get('teams', []):
            if t['team_number'] == team_num:
                team_data = t
                break
        
        if not team_data:
            return
        
        self.detail_text.delete('1.0', tk.END)
        
        detail = f"Team {team_num}: {team_data['team_name']}\n"
        detail += "=" * 80 + "\n\n"
        
        # OPR Data
        opr_data = team_data.get('opr_data') or {}
        detail += "OPR Data (Event-level):\n"
        detail += f"  OPR:  {opr_data.get('opr', 'N/A')}\n"
        detail += f"  DPR:  {opr_data.get('dpr', 'N/A')}\n"
        detail += f"  CCWM: {opr_data.get('ccwm', 'N/A')}\n\n"
        
        # Per-match EPA history
        epa_history = team_data.get('match_epa_history') or []
        detail += f"Per-Match EPA History ({len(epa_history)} matches):\n"
        detail += "-" * 80 + "\n"
        detail += f"{'Match':<8} {'Comp':<6} {'Alliance':<8} {'Total':<8} {'Auto':<8} {'Teleop':<8} {'Endgame':<8}\n"
        detail += "-" * 80 + "\n"
        
        for match in epa_history:
            match_num = match.get('match_number', 'N/A')
            comp_level = match.get('comp_level', 'N/A')
            alliance = match.get('alliance', 'N/A')
            epa = match.get('epa', {})
            
            total = epa.get('total_points', 'N/A')
            auto = epa.get('auto_points', 'N/A')
            teleop = epa.get('teleop_points', 'N/A')
            endgame = epa.get('endgame_points', 'N/A')
            
            total_str = f"{total:.1f}" if isinstance(total, (int, float)) else str(total)
            auto_str = f"{auto:.1f}" if isinstance(auto, (int, float)) else str(auto)
            teleop_str = f"{teleop:.1f}" if isinstance(teleop, (int, float)) else str(teleop)
            endgame_str = f"{endgame:.1f}" if isinstance(endgame, (int, float)) else str(endgame)
            
            detail += f"{match_num:<8} {comp_level:<6} {alliance:<8} {total_str:<8} {auto_str:<8} {teleop_str:<8} {endgame_str:<8}\n"
        
        detail += "\n" + "=" * 80 + "\n"
        detail += "Raw JSON:\n"
        detail += json.dumps(team_data, indent=2)
        
        self.detail_text.insert('1.0', detail)


def main():
    root = tk.Tk()
    app = EPAOPRHistoryTester(root)
    root.mainloop()


if __name__ == "__main__":
    main()
