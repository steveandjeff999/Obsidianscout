import json
import os
from flask import current_app


def _prefs_path():
    p = os.path.join(current_app.instance_path, 'user_prefs.json')
    return p


def _ensure_folder():
    inst = getattr(current_app, 'instance_path', None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'instance')
    if not os.path.exists(inst):
        os.makedirs(inst, exist_ok=True)


def load_prefs():
    _ensure_folder()
    p = _prefs_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_prefs(d):
    _ensure_folder()
    p = _prefs_path()
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d or {}, f, indent=2, default=str)


def get_user_prefs(username):
    d = load_prefs()
    return d.get(str(username), {})


def get_pref(username, key, default=None):
    prefs = get_user_prefs(username) or {}
    return prefs.get(key, default)


def set_pref(username, key, value):
    d = load_prefs()
    s = d.get(str(username), {})
    s[key] = value
    d[str(username)] = s
    try:
        save_prefs(d)
        return True
    except Exception:
        return False


def delete_pref(username, key):
    d = load_prefs()
    s = d.get(str(username), {})
    if key in s:
        del s[key]
    d[str(username)] = s
    try:
        save_prefs(d)
        return True
    except Exception:
        return False
