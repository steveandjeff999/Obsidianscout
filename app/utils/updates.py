import os
import json
import re
import math
from datetime import datetime
from flask import current_app

FILENAME_SAFE = re.compile(r'[^a-zA-Z0-9\-_]')


def _updates_folder() -> str:
    """Return the path to the instance/updates folder (create if missing)."""
    inst = getattr(current_app, 'instance_path', None) or os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'instance')
    folder = os.path.join(inst, 'updates')
    os.makedirs(folder, exist_ok=True)
    return folder


def _slugify(text: str) -> str:
    s = (text or '').strip().lower()
    # replace spaces with dashes, remove unsafe chars
    s = re.sub(r'\s+', '-', s)
    s = FILENAME_SAFE.sub('', s)
    return s or 'post'


def _safe_filename(title: str) -> str:
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    slug = _slugify(title)
    return f"{ts}_{slug}.json"


def list_posts() -> list:
    """Return list of post dicts sorted by created_at desc.
    Each dict contains: title, date, excerpt, filename, created_at, updated_at, author, published
    """
    folder = _updates_folder()
    posts = []
    for fn in sorted(os.listdir(folder), reverse=True):
        if not fn.lower().endswith('.json'):
            continue
        path = os.path.join(folder, fn)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data.setdefault('filename', fn)
            # Normalize date fields
            if 'date' not in data or not data['date']:
                data['date'] = data.get('created_at', '')[:10]

            # Compute approximate read time from word count (200 wpm baseline)
            body = (data.get('body') or '')
            word_count = len(re.findall(r"\w+", body))
            if word_count > 0:
                minutes = max(1, math.ceil(word_count / 200))
                data['read_time'] = f"{minutes} min read" if minutes > 1 else "1 min read"
            else:
                data['read_time'] = None

            posts.append(data)
        except Exception:
            continue

    # Sort by created_at if present, else by filename
    def _key(p):
        try:
            return p.get('created_at') or p.get('date') or p.get('filename')
        except Exception:
            return p.get('filename')

    posts = sorted(posts, key=_key, reverse=True)
    return posts


def load_post(filename: str) -> dict | None:
    folder = _updates_folder()
    # sanitize filename to avoid path traversal
    safe = os.path.basename(filename)
    if '..' in safe or '/' in safe or '\\' in safe:
        return None
    path = os.path.join(folder, safe)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('filename', safe)
        return data
    except Exception:
        return None


def save_post(data: dict, filename: str | None = None) -> str:
    """Save post data (dict). If filename provided, overwrite; otherwise create new file.
    Returns the filename used.
    Fields handled: title, date, excerpt, body, author, published
    """
    folder = _updates_folder()
    now = datetime.utcnow().isoformat() + 'Z'
    post = {
        'title': (data.get('title') or '').strip(),
        'date': (data.get('date') or '').strip(),
        'excerpt': (data.get('excerpt') or '').strip(),
        'body': data.get('body') or '',
        'author': data.get('author') or '',
        'published': bool(data.get('published', True)),
    }
    if filename:
        safe = os.path.basename(filename)
    else:
        safe = _safe_filename(post['title'] or 'post')
    path = os.path.join(folder, safe)

    # preserve created_at when overwriting
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            post['created_at'] = existing.get('created_at', now)
        except Exception:
            post['created_at'] = now
    else:
        post['created_at'] = now

    post['updated_at'] = now

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(post, f, ensure_ascii=False, indent=2)

    return safe


def delete_post(filename: str) -> bool:
    folder = _updates_folder()
    safe = os.path.basename(filename)
    path = os.path.join(folder, safe)
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return False
