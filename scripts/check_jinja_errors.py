#!/usr/bin/env python3
"""
Simple crawler to log in and crawl site for Jinja2 rendering errors.

Usage:
  python scripts/check_jinja_errors.py --base https://localhost:8080 --username "Seth Herod" --password 5454 --team 5454

This script will only try to POST to /auth/login and then crawl internal links.
It checks for "jinja2.exceptions" and common keywords like "UndefinedError" and "getattr".
"""
# Default configuration: set these so you can run the script without CLI args
DEFAULT_BASE = 'https://localhost:8080'
DEFAULT_USERNAME = 'Seth Herod'
DEFAULT_PASSWORD = '5454'
DEFAULT_TEAM = '5454'
DEFAULT_VERIFY = False  # do not verify SSL cert by default for local dev
DEFAULT_MAX_PAGES = 200
import argparse
import re
import sys
import urllib.parse
from collections import deque
import requests
from html import unescape
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def parse_links(html, base_url):
    # crude href parser to avoid new dependency
    hrefs = re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"']", html, flags=re.I)
    # Also gather form actions and link-like tags
    hrefs += re.findall(r"<link[^>]+href=[\"']([^\"']+)[\"']", html, flags=re.I)
    hrefs += re.findall(r"<form[^>]+action=[\"']([^\"']*)[\"']", html, flags=re.I)
    links = set()
    for href in hrefs:
        # ignore anchors and javascript
        if href.startswith('#') or href.lower().startswith('javascript:'):
            continue
        # resolve relative urls
        full = urllib.parse.urljoin(base_url, unescape(href))
        links.add(full)
    return links


def is_internal(url, base_netloc):
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc == base_netloc or parsed.netloc == ''


def collect_routes_from_code(routes_dir='app/routes'):
    """Collect route patterns from Python files under app/routes.

    This is a heuristic: it looks for @bp.route(...) and @app.route(...) decorators
    and extracts the first string literal path argument.
    """
    import os
    patterns = set()
    route_re = re.compile(r"@(?:\w+)\.route\((['\"])((?:\\.|(?!\1).)*)\1")
    # Also handle @bp.route('/foo', methods=[...]) or @bp.route('/foo')
    for root, _, files in os.walk(routes_dir):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    content = fh.read()
            except Exception:
                continue
            for m in route_re.finditer(content):
                route = m.group(2)
                # ignore blueprint registration placeholders or empty strings
                if not route or route.strip() == '':
                    continue
                patterns.add(route)
    return list(patterns)


def substitute_route(route):
    """Replace Flask dynamic route segments with test-friendly values.

    Examples:
      /users/<int:user_id> -> /users/1
      /events/<event_key> -> /events/test
      /files/<path:filename> -> /files/test
    """
    # Replace <int:...>, <float:...>, <path:...>, <uuid:...> -> 1
    route = re.sub(r"<\s*(?:int|float|uuid|path)\s*:[^>]+>", "1", route)
    # Replace <any('a','b')> -> the first option
    def any_sub(m):
        inner = m.group(1)
        choices = [c.strip().strip("'\" ") for c in inner.split(',') if c.strip()]
        return choices[0] if choices else 'test'
    route = re.sub(r"<\s*any\s*\(\s*([^)]*)\)\s*>", any_sub, route)
    # Replace remaining generic <...> -> 'test'
    route = re.sub(r"<[^>]+>", "test", route)
    # strip double slashes
    route = re.sub(r"//+", "/", route)
    if not route.startswith('/'):
        route = '/' + route
    return route


def login(session, base_url, username, password, team, verify=True):
    login_url = urllib.parse.urljoin(base_url, '/auth/login')
    # fetch login page first
    r = session.get(login_url, verify=verify, allow_redirects=True)
    r.raise_for_status()
    data = {
        'username': username,
        'password': password,
        'team_number': team,
        'remember_me': 'on'
    }
    # Submit login form
    post = session.post(login_url, data=data, verify=verify, allow_redirects=True)
    # If we are redirected to login page again or the login form still appears,
    # the login likely failed.
    if '/auth/login' in post.url or 'name="username"' in post.text:
        raise RuntimeError('Login failed; check credentials')
    return True


def crawl(base_url, session, verify=False, max_pages=200):
    base = urllib.parse.urlparse(base_url)
    base_netloc = base.netloc
    visited = set()
    findings = []
    # start with a queue seeded from the base URL and known routes in code
    queue = deque([base_url])
    try:
        routes = collect_routes_from_code('app/routes')
        logging.info('Discovered %d route patterns from code', len(routes))
        for r in routes:
            full = urllib.parse.urljoin(base_url, substitute_route(r))
            queue.append(full)
    except Exception as e:
        logging.debug('Failed to discover routes from code: %s', e)
    count = 0
    error_patterns = [re.compile(r'jinja2\\.exceptions', re.I), re.compile(r'UndefinedError', re.I), re.compile(r"getattr\(")]

    while queue and count < max_pages:
        url = queue.popleft()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            continue
        if url in visited:
            continue
        visited.add(url)
        count += 1
        logging.info('GET %s', url)
        try:
            r = session.get(url, verify=verify, allow_redirects=True, timeout=10)
        except Exception as e:
            findings.append({'url': url, 'error': str(e)})
            continue
        entry = {'url': url, 'status': r.status_code}
        # check page body for error signatures
        body = (r.text or '')
        if r.status_code >= 500:
            entry['server_error'] = True
            entry['body_snippet'] = body[:200]
        for pat in error_patterns:
            if pat.search(body):
                entry.setdefault('jinja_errors', []).append(pat.pattern)
        findings.append(entry)
        # extract links and add to queue
        links = parse_links(body, url)
        for l in links:
            if is_internal(l, base_netloc):
                # normalize - strip query string
                parsed_l = urllib.parse.urlparse(l)
                normalized = urllib.parse.urlunparse(parsed_l._replace(query='', fragment=''))
                if normalized not in visited:
                    queue.append(normalized)
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=False, help='Base URL (example https://localhost:8080)')
    parser.add_argument('--username', required=False)
    parser.add_argument('--password', required=False)
    parser.add_argument('--team', required=False)
    parser.add_argument('--verify', action='store_true', default=None, help='Enable SSL verification (default: disabled for local dev)')
    parser.add_argument('--max-pages', type=int, default=200)
    args = parser.parse_args()
    verify = args.verify if args.verify is not None else DEFAULT_VERIFY
    base = args.base or DEFAULT_BASE
    username = args.username or DEFAULT_USERNAME
    password = args.password or DEFAULT_PASSWORD
    team = args.team or DEFAULT_TEAM
    max_pages = args.max_pages or DEFAULT_MAX_PAGES

    s = requests.Session()
    # Set a desktop-like UA
    s.headers.update({'User-Agent': 'ObsidianScout-Crawler/1.0'})
    try:
        login(s, base, username, password, team, verify=verify)
        logging.info('Login successful')
    except Exception as e:
        logging.error('Login failed: %s', e)
        sys.exit(1)

    findings = crawl(base, s, verify=verify, max_pages=max_pages)
    # print report
    issues = [f for f in findings if f.get('jinja_errors') or f.get('status', 0) >= 500 or f.get('error')]
    if not issues:
        logging.info('No Jinja2 rendering errors detected across %d pages', len(findings))
    else:
        logging.warning('Found %d potential issues:', len(issues))
        for i in issues:
            logging.warning('%s - %s', i.get('status', 'ERR'), i.get('url'))
            if i.get('jinja_errors'):
                logging.warning('  Jinja matches: %s', i.get('jinja_errors'))
            if i.get('error'):
                logging.warning('  Error: %s', i.get('error'))
            if i.get('body_snippet'):
                logging.warning('  Body snippet: %s', i.get('body_snippet'))


if __name__ == '__main__':
    main()
