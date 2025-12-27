"""Tkinter test UI for mobile alliance endpoints

Developer test harness to exercise:
 - GET /api/mobile/alliances
 - POST /api/mobile/alliances
 - POST /api/mobile/alliances/<id>/invite
 - POST /api/mobile/invitations/<id>/respond
 - POST /api/mobile/alliances/<id>/toggle

Defaults to https://localhost; provides an option to disable TLS verification
for self-signed certs on local dev servers.

Usage:
    & "<venv>/Scripts/python.exe" tools/tk_mobile_alliances_ui.py
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

DEFAULT_BASE = "https://localhost"


class AlliancesTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mobile API: Alliances Tester")
        self.geometry("900x700")
        # Prevent the window from being resized smaller than layout requires
        try:
            self.minsize(900, 700)
        except Exception:
            pass

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(frm, text="Server base URL:").grid(column=0, row=row, sticky=tk.W)
        self.base_entry = ttk.Entry(frm, width=60)
        self.base_entry.insert(0, DEFAULT_BASE)
        self.base_entry.grid(column=1, row=row, sticky=tk.W)

        # TLS verify checkbox (allow self-signed locally)
        self.verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Verify TLS cert", variable=self.verify_var).grid(column=2, row=row, sticky=tk.W)

        ttk.Label(frm, text="Bearer token:").grid(column=0, row=row+1, sticky=tk.W)
        self.token_entry = ttk.Entry(frm, width=60)
        self.token_entry.grid(column=1, row=row+1, sticky=tk.W)
        # Login dialog button (opens a small modal to enter credentials and fetch token)
        self.login_button = ttk.Button(frm, text="Login...", command=self.open_login_window)
        self.login_button.grid(column=2, row=row+1, sticky=tk.W)

        # Alliance creation
        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(column=0, row=row+2, columnspan=3, sticky=(tk.E, tk.W), pady=8)
        ttk.Label(frm, text="Create alliance (admin user):").grid(column=0, row=row+3, sticky=tk.W)
        self.name_entry = ttk.Entry(frm, width=40)
        self.name_entry.grid(column=1, row=row+3, sticky=tk.W)
        self.desc_entry = ttk.Entry(frm, width=40)
        self.desc_entry.grid(column=1, row=row+4, sticky=tk.W)
        self.create_btn = ttk.Button(frm, text="Create Alliance", command=self.on_create)
        self.create_btn.grid(column=2, row=row+3, rowspan=2, sticky=tk.W)

        # My Joined Alliances header and list (with scrollbar)
        ttk.Label(frm, text="My Joined Alliances:").grid(column=0, row=row+6, sticky=tk.W)
        # Refresh button for alliances
        self.refresh_btn = ttk.Button(frm, text="Refresh Alliances", command=self.on_refresh)
        self.refresh_btn.grid(column=1, row=row+6, sticky=tk.W)
        # Add Active column and config status
        self.alliances_list = ttk.Treeview(frm, columns=("id", "name", "members", "active", "config"), show='headings', selectmode='browse')
        self.alliances_list.heading('id', text='ID')
        self.alliances_list.heading('name', text='Name')
        self.alliances_list.heading('members', text='Members')
        self.alliances_list.heading('active', text='Active')
        self.alliances_list.heading('config', text='Config Status')
        self.alliances_list.column('id', width=60)
        self.alliances_list.column('name', width=240)
        self.alliances_list.column('members', width=80)
        self.alliances_list.column('active', width=60)
        self.alliances_list.column('config', width=120)
        self.alliances_list.grid(column=0, row=row+7, columnspan=3, sticky=(tk.N, tk.S, tk.E, tk.W))
        # Vertical scrollbar for alliances list (keeps list visible and reachable)
        self.alliances_vscroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self.alliances_list.yview)
        self.alliances_list.configure(yscrollcommand=self.alliances_vscroll.set)
        self.alliances_vscroll.grid(column=3, row=row+7, rowspan=2, sticky=(tk.N, tk.S))
        frm.rowconfigure(row+7, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(3, weight=0)

        # Invite controls
        ttk.Label(frm, text="Invite team #:").grid(column=0, row=row+8, sticky=tk.W)
        self.invite_team_entry = ttk.Entry(frm, width=20)
        self.invite_team_entry.grid(column=1, row=row+8, sticky=tk.W)
        self.invite_btn = ttk.Button(frm, text="Send Invite", command=self.on_invite)
        self.invite_btn.grid(column=2, row=row+8, sticky=tk.W)

        # Activate/Deactivate buttons (operate on selected alliance)
        self.remove_shared_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Remove shared data on deactivate", variable=self.remove_shared_var).grid(column=0, row=row+9, sticky=tk.W)
        self.activate_btn = ttk.Button(frm, text="Activate Selected", command=self.on_activate)
        self.activate_btn.grid(column=1, row=row+9, sticky=tk.W)
        self.deactivate_btn = ttk.Button(frm, text="Deactivate Selected", command=self.on_deactivate)
        self.deactivate_btn.grid(column=2, row=row+9, sticky=tk.W)
        # Leave alliance button (allows leaving a selected joined alliance)
        self.leave_btn = ttk.Button(frm, text="Leave Selected", command=self.on_leave)
        self.leave_btn.grid(column=3, row=row+9, sticky=tk.W)

        # Invitations area
        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(column=0, row=row+10, columnspan=3, sticky=(tk.E, tk.W), pady=8)
        ttk.Label(frm, text="Pending Invitations:").grid(column=0, row=row+11, sticky=tk.W)
        # Add alliance_name column for clarity
        self.invitations_list = ttk.Treeview(frm, columns=("id", "alliance_id", "alliance_name", "from_team"), show='headings')
        self.invitations_list.heading('id', text='ID')
        self.invitations_list.heading('alliance_id', text='Alliance ID')
        self.invitations_list.heading('alliance_name', text='Alliance Name')
        self.invitations_list.heading('from_team', text='From Team')
        self.invitations_list.column('id', width=60)
        self.invitations_list.column('alliance_id', width=80)
        self.invitations_list.column('alliance_name', width=240)
        self.invitations_list.column('from_team', width=80)
        self.invitations_list.grid(column=0, row=row+12, columnspan=3, sticky=(tk.N, tk.S, tk.E, tk.W))
        # Vertical scrollbar for invitations list
        self.invitations_vscroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self.invitations_list.yview)
        self.invitations_list.configure(yscrollcommand=self.invitations_vscroll.set)
        self.invitations_vscroll.grid(column=3, row=row+12, rowspan=2, sticky=(tk.N, tk.S))
        frm.rowconfigure(row+12, weight=0)

        self.accept_btn = ttk.Button(frm, text="Accept", command=lambda: self.on_respond('accept'))
        self.accept_btn.grid(column=0, row=row+13, sticky=tk.W)
        self.decline_btn = ttk.Button(frm, text="Decline", command=lambda: self.on_respond('decline'))
        self.decline_btn.grid(column=1, row=row+13, sticky=tk.W)

        # Results output
        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(column=0, row=row+14, columnspan=3, sticky=(tk.E, tk.W), pady=8)
        # Keep results area compact so the joined alliances section remains visible
        self.results = scrolledtext.ScrolledText(frm, wrap=tk.WORD, height=10)
        self.results.grid(column=0, row=row+15, columnspan=3, sticky=(tk.N, tk.S, tk.E, tk.W))
        frm.rowconfigure(row+15, weight=0)

        # Small note
        ttk.Label(frm, text="Note: disable TLS verification for self-signed localhost certs").grid(column=0, row=row+16, columnspan=3, sticky=tk.W)

    def append_text(self, text: str):
        self.results.insert(tk.END, text + "\n")
        self.results.see(tk.END)

    def _headers(self):
        headers = {'Accept': 'application/json'}
        token = self.token_entry.get().strip()
        if token:
            headers['Authorization'] = f"Bearer {token}"
        return headers

    def _verify(self):
        return self.verify_var.get()

    def open_login_window(self):
        """Open a small modal to collect username/password/team and perform login"""
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return

        win = tk.Toplevel(self)
        win.title("Mobile Login")
        win.resizable(False, False)

        ttk.Label(win, text="Username:").grid(column=0, row=0, sticky=tk.W, padx=8, pady=(8,4))
        self.login_username_entry = ttk.Entry(win, width=30)
        self.login_username_entry.grid(column=1, row=0, sticky=tk.W, padx=8, pady=(8,4))

        ttk.Label(win, text="Password:").grid(column=0, row=1, sticky=tk.W, padx=8, pady=4)
        self.login_password_entry = ttk.Entry(win, width=30, show='*')
        self.login_password_entry.grid(column=1, row=1, sticky=tk.W, padx=8, pady=4)

        ttk.Label(win, text="Team number (optional):").grid(column=0, row=2, sticky=tk.W, padx=8, pady=4)
        self.login_team_entry = ttk.Entry(win, width=20)
        self.login_team_entry.grid(column=1, row=2, sticky=tk.W, padx=8, pady=4)

        btn = ttk.Button(win, text="Login", command=lambda: self._on_login_from_window(win))
        btn.grid(column=1, row=3, sticky=tk.E, padx=8, pady=(4,8))

        win.transient(self)
        win.grab_set()
        self.login_win = win

    def _on_login_from_window(self, win):
        username = self.login_username_entry.get().strip()
        password = self.login_password_entry.get().strip()
        team = self.login_team_entry.get().strip()
        if not username or not password:
            messagebox.showwarning("Missing fields", "Please enter username and password")
            return
        # disable the login button in the modal to prevent double submit
        for c in win.winfo_children():
            try:
                c.config(state='disabled')
            except Exception:
                pass
        threading.Thread(target=self._login_thread, args=(username, password, team, win), daemon=True).start()

    def _login_thread(self, username, password, team, win=None):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/auth/login"
            payload = {'username': username, 'password': password}
            if team:
                payload['team_number'] = team

            self.append_text(f"POST {url}\nPayload: {{'username':'***','team_number':'{team}'}}")
            resp = requests.post(url, json=payload, timeout=15, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}

            self.append_text(f"Status: {resp.status_code}\n{json.dumps(body, indent=2, ensure_ascii=False)}")

            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                token = body.get('token')
                if token:
                    self.token_entry.delete(0, tk.END)
                    self.token_entry.insert(0, token)
                messagebox.showinfo("Login successful", "Token stored in token field")
                if win:
                    try:
                        win.destroy()
                    except Exception:
                        pass
            else:
                messagebox.showerror("Login failed", f"Status {resp.status_code}: {body.get('error') if isinstance(body, dict) else str(body)}")
        except Exception as e:
            self.append_text(f"Login error: {str(e)}\n{traceback.format_exc()}")
        finally:
            # Re-enable login button(s) in modal if still present
            if win and getattr(win, 'winfo_exists', lambda: False)():
                for c in win.winfo_children():
                    try:
                        c.config(state='normal')
                    except Exception:
                        pass
            try:
                self.login_button.config(state='normal')
            except Exception:
                pass

    def on_refresh(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        self.refresh_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/alliances"
            self.append_text(f"GET {url}")
            resp = requests.get(url, headers=self._headers(), timeout=20, verify=self._verify())
            body = None
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}

            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")

            # Populate alliances list and invitations
            for i in self.alliances_list.get_children():
                self.alliances_list.delete(i)
            for i in self.invitations_list.get_children():
                self.invitations_list.delete(i)

            if isinstance(body, dict) and body.get('success'):
                for a in body.get('my_alliances', []):
                    cfg_status = a.get('config_status') or ('complete' if a.get('is_config_complete') else 'incomplete')
                    self.alliances_list.insert('', 'end', values=(a.get('id'), a.get('name'), a.get('member_count'), 'Yes' if a.get('is_active') else 'No', cfg_status))
                for inv in body.get('pending_invitations', []):
                    # Insert the alliance_name if present for better clarity
                    self.invitations_list.insert('', 'end', values=(inv.get('id'), inv.get('alliance_id'), inv.get('alliance_name'), inv.get('from_team')))
        except Exception as e:
            self.append_text(f"Error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.refresh_btn.config(state=tk.NORMAL)

    def on_create(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        name = (self.name_entry.get() or '').strip()
        desc = (self.desc_entry.get() or '').strip()
        if not name:
            messagebox.showwarning("Missing", "Alliance name is required")
            return
        self.create_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._create_thread, args=(name, desc), daemon=True).start()

    def _create_thread(self, name, desc):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/alliances"
            payload = {'name': name, 'description': desc}
            self.append_text(f"POST {url} payload={payload}")
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=20, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}
            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")
            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                messagebox.showinfo("Created", f"Alliance created id={body.get('alliance_id')}")
                self.on_refresh()
        except Exception as e:
            self.append_text(f"Create error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.create_btn.config(state=tk.NORMAL)

    def _selected_alliance_id(self):
        sel = self.alliances_list.selection()
        if not sel:
            return None
        try:
            return int(self.alliances_list.item(sel[0], 'values')[0])
        except Exception:
            return None

    def on_invite(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        alliance_id = self._selected_alliance_id()
        if not alliance_id:
            messagebox.showwarning("Select", "Please select an alliance first")
            return
        dest = self.invite_team_entry.get().strip()
        if not dest:
            messagebox.showwarning("Missing", "team_number is required")
            return
        try:
            dest = int(dest)
        except Exception:
            messagebox.showwarning("Invalid", "team_number must be an integer")
            return
        self.invite_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._invite_thread, args=(alliance_id, dest), daemon=True).start()

    def _invite_thread(self, alliance_id, dest_team):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/alliances/{alliance_id}/invite"
            payload = {'team_number': dest_team}
            self.append_text(f"POST {url} payload={payload}")
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=20, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}
            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")
            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                messagebox.showinfo("Invited", f"Team {dest_team} invited")
                self.on_refresh()
        except Exception as e:
            self.append_text(f"Invite error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.invite_btn.config(state=tk.NORMAL)

    def on_activate(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        alliance_id = self._selected_alliance_id()
        if not alliance_id:
            messagebox.showwarning("Select", "Please select an alliance first")
            return
        self.activate_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._activate_thread, args=(alliance_id,), daemon=True).start()

    def _activate_thread(self, alliance_id):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/alliances/{alliance_id}/toggle"
            payload = {'activate': True}
            self.append_text(f"POST {url} payload={payload}")
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=20, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}
            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")
            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                messagebox.showinfo("Activated", body.get('message'))
                self.on_refresh()
        except Exception as e:
            self.append_text(f"Activate error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.activate_btn.config(state=tk.NORMAL)

    def on_deactivate(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        alliance_id = self._selected_alliance_id()
        if not alliance_id:
            messagebox.showwarning("Select", "Please select an alliance first")
            return
        remove_shared = bool(self.remove_shared_var.get())
        self.deactivate_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._deactivate_thread, args=(alliance_id, remove_shared), daemon=True).start()

    def on_leave(self):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        alliance_id = self._selected_alliance_id()
        if not alliance_id:
            messagebox.showwarning("Select", "Please select an alliance first")
            return
        if not messagebox.askyesno("Confirm", "Are you sure you want to leave the selected alliance?"):
            return
        self.leave_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._leave_thread, args=(alliance_id,), daemon=True).start()

    def _deactivate_thread(self, alliance_id, remove_shared):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/alliances/{alliance_id}/toggle"
            payload = {'activate': False, 'remove_shared_data': bool(remove_shared)}
            self.append_text(f"POST {url} payload={payload}")
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=20, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}
            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")
            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                messagebox.showinfo("Deactivated", body.get('message'))
                self.on_refresh()
        except Exception as e:
            self.append_text(f"Deactivate error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.deactivate_btn.config(state=tk.NORMAL)

    def _selected_invitation_id(self):
        sel = self.invitations_list.selection()
        if not sel:
            return None
        try:
            return int(self.invitations_list.item(sel[0], 'values')[0])
        except Exception:
            return None

    def on_respond(self, response):
        if requests is None:
            messagebox.showerror("Missing dependency", "The 'requests' library is required. Install it: pip install requests")
            return
        inv_id = self._selected_invitation_id()
        if not inv_id:
            messagebox.showwarning("Select", "Please select an invitation first")
            return
        self.accept_btn.config(state=tk.DISABLED)
        self.decline_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._respond_thread, args=(inv_id, response), daemon=True).start()

    def _respond_thread(self, inv_id, response):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/invitations/{inv_id}/respond"
            payload = {'response': response}
            self.append_text(f"POST {url} payload={payload}")
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=20, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}
            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")
            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                messagebox.showinfo("Responded", f"Invitation {inv_id} {response}")
                self.on_refresh()
        except Exception as e:
            self.append_text(f"Respond error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.accept_btn.config(state=tk.NORMAL)
            self.decline_btn.config(state=tk.NORMAL)

    def _leave_thread(self, alliance_id):
        try:
            base = self.base_entry.get().strip().rstrip('/')
            url = f"{base}/api/mobile/alliances/{alliance_id}/leave"
            self.append_text(f"POST {url} (leave alliance)")
            resp = requests.post(url, headers=self._headers(), timeout=20, verify=self._verify())
            try:
                body = resp.json()
            except Exception:
                body = {'text': resp.text}
            self.append_text(f"Status: {resp.status_code} {json.dumps(body, indent=2, ensure_ascii=False)}")
            if resp.status_code == 200 and isinstance(body, dict) and body.get('success'):
                messagebox.showinfo("Left", body.get('message') or f"Left alliance {alliance_id}")
                self.on_refresh()
        except Exception as e:
            self.append_text(f"Leave error: {str(e)}\n{traceback.format_exc()}")
        finally:
            try:
                self.leave_btn.config(state=tk.NORMAL)
            except Exception:
                pass


def main():
    app = AlliancesTester()
    app.mainloop()


if __name__ == '__main__':
    main()
