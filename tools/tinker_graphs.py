"""
Tinker UI for requesting graph images from the mobile API and displaying them.

Run this script locally. It will start a small Flask app at http://127.0.0.1:5001
which serves a UI you can use to run a set of pre-defined graph combinations
against your running OBSIDIAN Scout server. The UI will show returned PNGs
or JSON fallback/error messages.

Usage:
  # Activate your venv first
  python tools\tinker_graphs.py

Then open http://127.0.0.1:5001 in your browser.

Configuration:
  The script reads these environment variables (optional):
    OBSIDIAN_BASE_URL - base URL of the server (default: https://localhost:8080)
    OBSIDIAN_TEST_USERNAME - username to login with (default: Seth Herod)
    OBSIDIAN_TEST_PASSWORD - password (default: 5454)
    OBSIDIAN_TEST_TEAM - team number (default: 5454)

This is a developer tool — do not run it in production or expose it publicly.
"""
from flask import Flask, render_template, request, jsonify
import os
import requests
import base64
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, template_folder='templates')

# Config
BASE_URL = os.environ.get('OBSIDIAN_BASE_URL', 'https://localhost:8080')
API_BASE = f"{BASE_URL}/api/mobile"
TEST_USERNAME = os.environ.get('OBSIDIAN_TEST_USERNAME', 'Seth Herod')
TEST_PASSWORD = os.environ.get('OBSIDIAN_TEST_PASSWORD', '5454')
TEST_TEAM = int(os.environ.get('OBSIDIAN_TEST_TEAM', '5454'))

# Pre-defined combinations to exercise. Keep this reasonable to avoid long runs.
PLOTLY_GRAPH_TYPES = ['line', 'bar', 'radar', 'scatter']
METRICS = ['total_points', 'auto_points', 'teleop_points']
MODES = ['match_by_match', 'averages']
TEAM_SETS = [ [TEST_TEAM], [TEST_TEAM, 1234] ]

VIS_TYPES = ['team_performance', 'team_comparison', 'radar_chart', 'trend_chart']


def login():
    payload = {'username': TEST_USERNAME, 'password': TEST_PASSWORD, 'team_number': TEST_TEAM}
    r = requests.post(f"{API_BASE}/auth/login", json=payload, verify=False)
    if r.status_code != 200:
        return None, r.text
    data = r.json()
    return data.get('token'), None


def fetch_visualization(token, payload):
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    r = requests.post(f"{API_BASE}/graphs/visualize", json=payload, headers=headers, verify=False, stream=True)

    # Determine content type
    ctype = r.headers.get('Content-Type', '')
    if r.status_code == 200 and ctype.startswith('image/'):
        # Read bytes and return data URL
        img_bytes = r.content
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        return {'status': 'ok', 'type': 'image', 'data_url': f"data:{ctype};base64,{b64}"}
    else:
        # Try to decode JSON
        try:
            j = r.json()
        except Exception:
            j = {'status_code': r.status_code, 'text': r.text[:2000]}
        return {'status': 'ok', 'type': 'json', 'json': j, 'content_type': ctype}


@app.route('/')
def index():
    return render_template('tinker.html')


@app.route('/run_all', methods=['POST'])
def run_all():
    # Login first
    token, err = login()
    if not token:
        return jsonify({'success': False, 'error': 'Login failed', 'detail': err}), 500

    results = []

    # 1) Run Plotly-style combinations
    for teams in TEAM_SETS:
        for g in PLOTLY_GRAPH_TYPES:
            for m in METRICS:
                for mode in MODES:
                    name = f"plotly:{g}|metric={m}|mode={mode}|teams={','.join(map(str,teams))}"
                    payload = {
                        'team_numbers': teams,
                        'graph_type': g,
                        'metric': m,
                        'mode': mode
                    }
                    res = fetch_visualization(token, payload)
                    results.append({'name': name, 'payload': payload, 'result': res})

    # 2) Run Visualizer vis_type examples (single-team where appropriate)
    for vis in VIS_TYPES:
        name = f"visual:{vis}|team={TEST_TEAM}"
        payload = {'vis_type': vis, 'team_number': TEST_TEAM}
        res = fetch_visualization(token, payload)
        results.append({'name': name, 'payload': payload, 'result': res})

    return jsonify({'success': True, 'run_at': datetime.utcnow().isoformat() + 'Z', 'results': results}), 200


if __name__ == '__main__':
    # Run development server
    app.run(host='127.0.0.1', port=5001, debug=True)
