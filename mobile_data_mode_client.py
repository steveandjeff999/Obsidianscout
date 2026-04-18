import json
import ssl
import tkinter as tk
from tkinter import messagebox, scrolledtext
from typing import Any, Dict, Optional
import urllib.error
import urllib.request


def build_base_url(raw_host: str) -> Optional[str]:
    host = (raw_host or '').strip()
    if not host:
        return None
    if not host.startswith('http://') and not host.startswith('https://'):
        host = 'http://' + host
    return host.rstrip('/')


def request_json(url: str, payload: Optional[Dict[str, Any]] = None, token: Optional[str] = None) -> Dict[str, Any]:
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    data = None
    method = 'GET'
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        method = 'POST'

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    context = ssl._create_unverified_context() if url.startswith('https://') else None

    try:
        with urllib.request.urlopen(req, timeout=30, context=context) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8')
        except Exception:
            body = str(exc)
        raise RuntimeError(f'HTTP {exc.code}: {body}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Connection error: {exc}') from exc


def run_gui() -> None:
    root = tk.Tk()
    root.title('Mobile API Current Data Mode Client')
    root.geometry('760x620')
    root.resizable(True, True)

    tk.Label(root, text='Mobile API Login + Current Data Mode Match Points', font=('Segoe UI', 13, 'bold')).pack(pady=(12, 8))

    form = tk.Frame(root)
    form.pack(padx=16, pady=6, fill='x')

    tk.Label(form, text='Server address:', anchor='w').grid(row=0, column=0, sticky='w')
    host_var = tk.StringVar(value='127.0.0.1:8080')
    tk.Entry(form, textvariable=host_var, width=48).grid(row=0, column=1, pady=4, sticky='we')

    tk.Label(form, text='Login username:', anchor='w').grid(row=1, column=0, sticky='w')
    username_var = tk.StringVar(value='')
    tk.Entry(form, textvariable=username_var, width=48).grid(row=1, column=1, pady=4, sticky='we')

    tk.Label(form, text='Login password:', anchor='w').grid(row=2, column=0, sticky='w')
    password_var = tk.StringVar(value='')
    tk.Entry(form, textvariable=password_var, width=48, show='*').grid(row=2, column=1, pady=4, sticky='we')

    tk.Label(form, text='Login team number:', anchor='w').grid(row=3, column=0, sticky='w')
    login_team_var = tk.StringVar(value='')
    tk.Entry(form, textvariable=login_team_var, width=48).grid(row=3, column=1, pady=4, sticky='we')

    tk.Label(form, text='Target team number(s):', anchor='w').grid(row=4, column=0, sticky='w')
    target_teams_var = tk.StringVar(value='')
    tk.Entry(form, textvariable=target_teams_var, width=48).grid(row=4, column=1, pady=4, sticky='we')

    tk.Label(form, text='Event code or ID:', anchor='w').grid(row=5, column=0, sticky='w')
    event_var = tk.StringVar(value='')
    tk.Entry(form, textvariable=event_var, width=48).grid(row=5, column=1, pady=4, sticky='we')

    form.grid_columnconfigure(1, weight=1)

    status = tk.Label(root, text='Enter the server address and login credentials, then request match points.', wraplength=700, justify='left')
    status.pack(pady=(8, 10))

    output = scrolledtext.ScrolledText(root, wrap='word', height=22)
    output.pack(fill='both', expand=True, padx=16, pady=(0, 12))
    output.insert('end', 'Results will appear here.\n')
    output.configure(state='disabled')

    def set_output(text: str) -> None:
        output.configure(state='normal')
        output.delete('1.0', 'end')
        output.insert('end', text)
        output.configure(state='disabled')

    def do_login_and_fetch() -> None:
        base_url = build_base_url(host_var.get())
        username = username_var.get().strip()
        password = password_var.get()
        login_team_number = login_team_var.get().strip()
        target_team_numbers = target_teams_var.get().strip()
        event_value = event_var.get().strip()

        if not base_url or not username or not password or not login_team_number:
            messagebox.showwarning('Missing fields', 'Enter server address, login username, login password, and login team number.')
            return

        login_url = f'{base_url}/api/mobile/auth/login'
        try:
            login_resp = request_json(login_url, payload={
                'username': username,
                'password': password,
                'team_number': login_team_number,
            })
        except Exception as exc:
            messagebox.showerror('Login failed', str(exc))
            return

        if not login_resp.get('success'):
            messagebox.showerror('Login failed', json.dumps(login_resp, indent=2))
            return

        token = login_resp.get('token')
        if not token:
            messagebox.showerror('Login failed', 'Login response did not include a token.')
            return

        request_payload: Dict[str, Any] = {}
        if event_value:
            request_payload['event_id'] = event_value
        if target_team_numbers:
            if ',' in target_team_numbers:
                request_payload['team_numbers'] = [item.strip() for item in target_team_numbers.split(',') if item.strip()]
            else:
                request_payload['team_number'] = target_team_numbers

        points_url = f'{base_url}/api/mobile/config/game/current-data-mode'
        try:
            points_resp = request_json(points_url, payload=request_payload if request_payload else None, token=token)
        except Exception as exc:
            messagebox.showerror('Match points request failed', str(exc))
            return

        login_user = (login_resp.get('user') or {})
        result = {
            'login': {
                'username': login_user.get('username', username),
                'team_number': login_user.get('team_number', login_team_number),
                'token': token,
            },
            'request': request_payload,
            'response': points_resp,
        }

        set_output(json.dumps(result, indent=2))
        status.config(text='Login succeeded and match-point estimates were fetched.')

    tk.Button(root, text='Login and Fetch Match Points', command=do_login_and_fetch, width=28).pack(pady=(0, 12))

    root.mainloop()


if __name__ == '__main__':
    run_gui()
