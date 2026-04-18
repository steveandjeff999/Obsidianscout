import json
import os
import ssl
import sys
import urllib.error
import urllib.request

import pytest

# Ensure the project root is on sys.path when running this file directly.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from app import create_app, db
except Exception as exc:
    print(f'Warning: failed to import app package: {exc}')
    create_app = None
    db = None

try:
    from app.models import User, ScoutingTeamSettings
    from app.routes import mobile_api as ma
    from app.models import Team, Event, Match, ScoutingData
except Exception:
    User = None
    ScoutingTeamSettings = None
    ma = None
    Team = None
    Event = None
    Match = None
    ScoutingData = None


def test_mobile_data_mode_returns_correct_mode_for_statbotics_plus_data():
    app = create_app()
    with app.app_context():
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        user = User(username='mobile_data_mode_user', scouting_team_number=9997)
        user.set_password('testpass')
        db.session.add(user)
        db.session.commit()

        settings = ScoutingTeamSettings.get_or_create_for_team(user.scouting_team_number)
        settings.epa_source = 'scouted_with_statbotics'
        db.session.commit()

        token = ma.create_token(user.id, user.username, user.scouting_team_number)
        resp = client.get('/api/mobile/config/game/data-mode', headers={'Authorization': f'Bearer {token}'})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') is True
        assert data.get('epa_source') == 'scouted_with_statbotics'
        assert data.get('data_mode') == 'Scouted Data + Statbotics EPA Gap-Fill'


def test_mobile_data_mode_defaults_to_data_when_no_team_settings():
    app = create_app()
    with app.app_context():
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        user = User(username='mobile_data_mode_user_default', scouting_team_number=9998)
        user.set_password('testpass')
        db.session.add(user)
        db.session.commit()

        token = ma.create_token(user.id, user.username, user.scouting_team_number)
        resp = client.get('/api/mobile/config/game/data-mode', headers={'Authorization': f'Bearer {token}'})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') is True
        assert data.get('epa_source') == 'scouted_only'
        assert data.get('data_mode') == 'Scouted Data Only'


def test_mobile_current_data_mode_match_points_returns_scouted_rows(monkeypatch):
    app = create_app()
    with app.app_context():
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        user = User(username='mobile_current_mode_user', scouting_team_number=9996)
        user.set_password('testpass')
        db.session.add(user)
        db.session.commit()

        settings = ScoutingTeamSettings.get_or_create_for_team(user.scouting_team_number)
        settings.epa_source = 'scouted_with_statbotics'
        db.session.commit()

        team_a = Team(team_number=1111, team_name='Team A', scouting_team_number=user.scouting_team_number)
        team_b = Team(team_number=2222, team_name='Team B', scouting_team_number=user.scouting_team_number)
        event = Event(name='Current Mode Event', code='CMODE', year=2026, scouting_team_number=user.scouting_team_number)
        db.session.add_all([team_a, team_b, event])
        db.session.flush()
        team_a.events.append(event)
        team_b.events.append(event)

        match_a = Match(match_number=1, match_type='Qualification', event_id=event.id, scouting_team_number=user.scouting_team_number)
        match_b = Match(match_number=2, match_type='Qualification', event_id=event.id, scouting_team_number=user.scouting_team_number)
        db.session.add_all([match_a, match_b])
        db.session.flush()

        db.session.add_all([
            ScoutingData(team_id=team_a.id, match_id=match_a.id, scouting_team_number=user.scouting_team_number, scout_name='Scout A', scout_id=user.id, data={'tot': 6}),
            ScoutingData(team_id=team_b.id, match_id=match_b.id, scouting_team_number=user.scouting_team_number, scout_name='Scout B', scout_id=user.id, data={'tot': 6}),
        ])
        db.session.commit()

        def fake_calculate_metric(self, formula_or_id):
            return {'apt': 1, 'tpt': 2, 'ept': 3, 'tot': 6}.get(formula_or_id, 0)

        monkeypatch.setattr(ScoutingData, 'calculate_metric', fake_calculate_metric, raising=False)
        monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa', lambda team_number: {'total': 42})

        token = ma.create_token(user.id, user.username, user.scouting_team_number)
        resp = client.get(f'/api/mobile/config/game/current-data-mode?event_id={event.id}', headers={'Authorization': f'Bearer {token}'})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') is True
        assert data.get('epa_source') == 'scouted_with_statbotics'
        assert data.get('data_mode') == 'Scouted Data + Statbotics EPA Gap-Fill'
        assert data.get('team_count') == 2
        assert len(data.get('teams', [])) == 2
        for team_payload in data['teams']:
            assert len(team_payload['match_points']) == 1
            match_payload = team_payload['match_points'][0]
            assert match_payload['scouted_total_points'] == 6
            assert match_payload['external_total_points'] == 42
            assert match_payload['selected_total_points'] == 6
            assert match_payload['selected_source'] == 'scouted'


def mobile_data_mode_login_ui():
    """Interactive helper: prompt for mobile auth login, then call data-mode endpoint."""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        raise RuntimeError('tkinter is not available')

    app = create_app()
    with app.app_context():
        try:
            db.create_all(bind_key='users')
        except Exception:
            pass
        try:
            db.create_all()
        except Exception:
            pass

        client = app.test_client()

        user = User(username='mobile_data_mode_ui_user', scouting_team_number=9999)
        user.set_password('testpass')
        db.session.add(user)
        db.session.commit()

        result = {'token': None, 'success': False}

        root = tk.Tk()
        root.title('Mobile API Login Test')
        root.geometry('380x250')
        root.resizable(False, False)

        tk.Label(root, text='Enter mobile credentials to log in', font=('Segoe UI', 11, 'bold')).pack(pady=(10, 5))

        frame = tk.Frame(root)
        frame.pack(padx=16, pady=8, fill='x')

        tk.Label(frame, text='Username:', anchor='w').grid(row=0, column=0, sticky='w')
        username_var = tk.StringVar(value='mobile_data_mode_ui_user')
        tk.Entry(frame, textvariable=username_var, width=36).grid(row=0, column=1, pady=4)

        tk.Label(frame, text='Password:', anchor='w').grid(row=1, column=0, sticky='w')
        password_var = tk.StringVar(value='testpass')
        tk.Entry(frame, textvariable=password_var, width=36, show='*').grid(row=1, column=1, pady=4)

        tk.Label(frame, text='Team Number:', anchor='w').grid(row=2, column=0, sticky='w')
        team_var = tk.StringVar(value='9999')
        tk.Entry(frame, textvariable=team_var, width=36).grid(row=2, column=1, pady=4)

        message_label = tk.Label(root, text='Click Login to authenticate and fetch data mode.', wraplength=340)
        message_label.pack(pady=(4, 8))

        def do_login():
            username = username_var.get().strip()
            password = password_var.get()
            team_number = team_var.get().strip()
            if not username or not password or not team_number:
                messagebox.showwarning('Missing fields', 'Please enter username, password, and team number.')
                return
            try:
                resp = client.post('/api/mobile/auth/login', json={
                    'username': username,
                    'password': password,
                    'team_number': team_number
                })
                data = resp.get_json() if resp.is_json else None
            except Exception as exc:
                messagebox.showerror('Request failed', str(exc))
                return

            if resp.status_code != 200 or not data or not data.get('success'):
                msg = data or resp.get_data(as_text=True)
                messagebox.showerror('Login failed', f'Status {resp.status_code}: {msg}')
                return

            token = data.get('token')
            if not token:
                messagebox.showerror('Login failed', 'Token was not returned by login endpoint.')
                return

            result['token'] = token
            result['success'] = True
            messagebox.showinfo('Login success', f"Authenticated as {username}.\n\nToken:\n{token[:64]}...")

            resp2 = client.get('/api/mobile/config/game/data-mode', headers={'Authorization': f'Bearer {token}'})
            if resp2.status_code == 200 and resp2.is_json:
                dm = resp2.get_json()
                messagebox.showinfo('Data Mode', f"Data mode response:\n{json.dumps(dm, indent=2)}")
            else:
                messagebox.showerror('Data mode failed', f"Status {resp2.status_code}: {resp2.get_data(as_text=True)}")
            root.quit()

        def on_close():
            root.quit()

        login_button = tk.Button(root, text='Login', command=do_login, width=18)
        login_button.pack(pady=(0, 12))
        root.protocol('WM_DELETE_WINDOW', on_close)

        root.mainloop()
        try:
            root.destroy()
        except Exception:
            pass

        if not result['success']:
            raise AssertionError('Interactive login did not complete successfully')
        return result


def mobile_data_mode_login_ui_remote():
    """Interactive test: prompt for server IP, login, and fetch data mode from remote API."""
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        raise RuntimeError('tkinter is not available')

    def build_url(raw_host):
        host = raw_host.strip()
        if not host:
            return None
        if not host.startswith('http://') and not host.startswith('https://'):
            host = 'http://' + host
        return host.rstrip('/')

    def request_json(url, payload=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST' if payload is not None else 'GET')
        context = None
        if url.startswith('https://'):
            context = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(req, timeout=30, context=context) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8')
            except Exception:
                body = str(exc)
            raise RuntimeError(f'HTTP {exc.code}: {body}')
        except urllib.error.URLError as exc:
            raise RuntimeError(f'Connection error: {exc}')

    root = tk.Tk()
    root.title('Mobile API Remote Login Test')
    root.geometry('420x320')
    root.resizable(False, False)

    tk.Label(root, text='Remote API Login', font=('Segoe UI', 12, 'bold')).pack(pady=(10, 6))

    frame = tk.Frame(root)
    frame.pack(padx=16, pady=8, fill='x')

    tk.Label(frame, text='Server address:', anchor='w').grid(row=0, column=0, sticky='w')
    host_var = tk.StringVar(value='127.0.0.1:8080')
    tk.Entry(frame, textvariable=host_var, width=40).grid(row=0, column=1, pady=4)

    tk.Label(frame, text='Username:', anchor='w').grid(row=1, column=0, sticky='w')
    username_var = tk.StringVar(value='mobile_data_mode_ui_user')
    tk.Entry(frame, textvariable=username_var, width=40).grid(row=1, column=1, pady=4)

    tk.Label(frame, text='Password:', anchor='w').grid(row=2, column=0, sticky='w')
    password_var = tk.StringVar(value='testpass')
    tk.Entry(frame, textvariable=password_var, width=40, show='*').grid(row=2, column=1, pady=4)

    tk.Label(frame, text='Team number:', anchor='w').grid(row=3, column=0, sticky='w')
    team_var = tk.StringVar(value='9999')
    tk.Entry(frame, textvariable=team_var, width=40).grid(row=3, column=1, pady=4)

    status_label = tk.Label(root, text='Enter server info and click Login.', wraplength=380)
    status_label.pack(pady=(6, 8))

    def do_login():
        host = build_url(host_var.get())
        username = username_var.get().strip()
        password = password_var.get()
        team_number = team_var.get().strip()

        if not host or not username or not password or not team_number:
            messagebox.showwarning('Missing fields', 'Please enter server address, username, password, and team number.')
            return

        login_url = f'{host}/api/mobile/auth/login'
        try:
            login_resp = request_json(login_url, payload={
                'username': username,
                'password': password,
                'team_number': team_number
            })
        except Exception as exc:
            messagebox.showerror('Login failed', str(exc))
            return

        if not login_resp.get('success'):
            messagebox.showerror('Login failed', json.dumps(login_resp, indent=2))
            return

        token = login_resp.get('token')
        if not token:
            messagebox.showerror('Login failed', 'No token returned by login endpoint.')
            return

        data_mode_url = f'{host}/api/mobile/config/game/data-mode'
        try:
            data_mode_resp = request_json(data_mode_url, token=token)
        except Exception as exc:
            messagebox.showerror('Data mode failed', str(exc))
            return

        messagebox.showinfo('Data Mode', f'Login succeeded.\n\nToken:\n{token[:64]}...\n\nResponse:\n{json.dumps(data_mode_resp, indent=2)}')

    login_button = tk.Button(root, text='Login to remote API', command=do_login, width=22)
    login_button.pack(pady=(0, 10))

    def on_close():
        root.quit()

    root.protocol('WM_DELETE_WINDOW', on_close)
    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.skipif(os.environ.get('MOBILE_API_UI_TEST') != '1', reason='Interactive Tkinter login test')
def test_mobile_data_mode_login_ui():
    mobile_data_mode_login_ui()


if __name__ == '__main__':
    mobile_data_mode_login_ui_remote()
