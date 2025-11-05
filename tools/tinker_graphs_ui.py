"""
Tinker UI: request many graph combinations from the mobile API and produce
an HTML gallery of results (images or JSON fallbacks).

Usage:
  - Set environment variables to configure or edit defaults below.
  - Run: python tools\tinker_graphs_ui.py
  - Open the generated HTML at tools/tinker_output/index.html

This script logs in, enumerates a set of sensible combinations (Plotly-style
and Visualizer-style), calls `/api/mobile/graphs/visualize` for each payload,
saves returned PNGs or JSON, and writes a simple HTML page showing results.
"""
import os
import json
import urllib3
import requests
from pathlib import Path
from datetime import datetime

# Configuration (can be overridden with environment variables)
BASE_URL = os.environ.get('OBSIDIAN_BASE_URL', 'https://localhost:8080')
API_BASE = f"{BASE_URL}/api/mobile"
# Use admin user which has scouting_team_number = 5454 and has actual data
USERNAME = os.environ.get('OBSIDIAN_TEST_USERNAME', 'admin')
PASSWORD = os.environ.get('OBSIDIAN_TEST_PASSWORD', '5454')
TEAM = int(os.environ.get('OBSIDIAN_TEST_TEAM', '5454'))

OUT_DIR = Path('tools') / 'tinker_output'
OUT_DIR.mkdir(parents=True, exist_ok=True)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login():
    payload = {"username": USERNAME, "password": PASSWORD, "team_number": TEAM}
    r = requests.post(f"{API_BASE}/auth/login", json=payload, verify=False)
    r.raise_for_status()
    data = r.json()
    if not data.get('success'):
        raise RuntimeError(f"Login failed: {data}")
    return data.get('token')


def save_bytes(name: str, content: bytes):
    p = OUT_DIR / name
    p.write_bytes(content)
    return p


def save_json(name: str, obj):
    p = OUT_DIR / name
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf-8')
    return p


def build_combinations():
    # Short lists to keep the total reasonable for a UI demo
    graph_types = ['line', 'bar', 'radar', 'scatter']
    metrics = ['total_points', 'auto_points', 'teleop_points', 'endgame_points']
    modes = ['match_by_match', 'averages']
    # Use team 5431 which actually has scouting data (scouted BY team 5454)
    team_sets = [[2583], [5431, 6369, 2583]]

    combos = []

    # Plotly-style combos
    for gt in graph_types:
        for metric in metrics:
            for mode in modes:
                for teams in team_sets:
                    combos.append({
                        'label': f'plotly {gt} metric={metric} mode={mode} teams={teams}',
                        'payload': {
                            'team_numbers': teams,
                            'graph_type': gt,
                            'metric': metric,
                            'mode': mode
                        }
                    })

    # Visualizer-style combos (vis_type)
    vis_types = [
        'team_performance','team_comparison','metric_comparison','match_breakdown',
        'radar_chart','event_summary','match_schedule','team_ranking','ranking_comparison','trend_chart'
    ]

    for vt in vis_types:
        for teams in team_sets:
            combos.append({
                'label': f'visualizer {vt} teams={teams}',
                'payload': {
                    'vis_type': vt,
                    'team_numbers': teams
                }
            })

    # Keep combos deterministic order
    return combos


def run():
    print('Tinker UI: logging in...')
    token = login()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    combos = build_combinations()

    results = []
    idx = 0
    for combo in combos:
        idx += 1
        label = combo['label']
        payload = combo['payload']
        print(f'[{idx}/{len(combos)}] Requesting: {label}')
        try:
            r = requests.post(f"{API_BASE}/graphs/visualize", json=payload, headers=headers, verify=False, timeout=30)
        except Exception as e:
            print('  Request failed:', e)
            results.append({'label': label, 'payload': payload, 'status': 'request_failed', 'error': str(e)})
            continue

        status = r.status_code
        ctype = r.headers.get('Content-Type', '')

        entry = {'label': label, 'payload': payload, 'status': status, 'content_type': ctype}

        if status == 200 and ctype.startswith('image/'):
            # Save image
            ext = '.png' if 'png' in ctype else '.bin'
            fname = f"{idx:03d}_{label.replace(' ', '_').replace('/', '_')}{ext}"
            # sanitize filename
            fname = ''.join(c for c in fname if c.isalnum() or c in ('_', '-', '.', ','))
            p = save_bytes(fname, r.content)
            entry['image'] = str(p)
            print('  Saved image ->', p)
        else:
            # Save JSON or raw text for inspection
            try:
                body = r.json()
                fname = f"{idx:03d}_{label.replace(' ', '_')}.json"
                fname = ''.join(c for c in fname if c.isalnum() or c in ('_', '-', '.', ','))
                p = save_json(fname, body)
                entry['json'] = str(p)
                print('  Saved JSON ->', p)
            except Exception:
                # Save raw body (probably HTML)
                fname = f"{idx:03d}_{label.replace(' ', '_')}.txt"
                fname = ''.join(c for c in fname if c.isalnum() or c in ('_', '-', '.', ','))
                p = save_bytes(fname, r.content)
                entry['raw'] = str(p)
                print('  Saved raw ->', p)

        results.append(entry)

    # Build HTML gallery
    html_parts = [
        '<!doctype html>',
        '<html><head><meta charset="utf-8"><title>Tinker Graphs UI</title>' +
        '<style>body{font-family:Arial,sans-serif;padding:20px} .item{display:inline-block;margin:10px;border:1px solid #ccc;padding:8px;width:300px;vertical-align:top} img{max-width:100%;height:auto;display:block}</style>' +
        '</head><body>' ,
        f'<h1>Tinker Graphs UI - {datetime.utcnow().isoformat()} UTC</h1>',
        '<p>Requests made to: <code>' + API_BASE + '/graphs/visualize</code></p>',
        '<div id="grid">'
    ]

    for r in results:
        html_parts.append('<div class="item">')
        html_parts.append(f'<h3>{r["label"]}</h3>')
        html_parts.append(f'<p>Status: {r.get("status")}</p>')
        if 'image' in r:
            rel = os.path.relpath(r['image'], OUT_DIR)
            html_parts.append(f'<img src="{rel}" alt="{r["label"]}">')
        elif 'json' in r:
            html_parts.append(f'<pre style="max-height:200px;overflow:auto">{json.dumps(json.load(open(r["json"],encoding="utf-8")), indent=2)}</pre>')
            html_parts.append(f'<p><a href="{os.path.basename(r["json"])}">Open JSON</a></p>')
        elif 'raw' in r:
            html_parts.append(f'<p>Raw output saved: <a href="{os.path.basename(r["raw"])}">{os.path.basename(r["raw"])}</a></p>')
        else:
            html_parts.append('<p>No content saved.</p>')
        html_parts.append('</div>')

    html_parts.append('</div></body></html>')
    index_path = OUT_DIR / 'index.html'
    index_path.write_text('\n'.join(html_parts), encoding='utf-8')

    print('\nDone. Open the gallery:')
    print(index_path.resolve())


if __name__ == '__main__':
    run()
