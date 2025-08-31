import json
import os
from datetime import datetime

NOTIFICATIONS_FILE = os.path.join('instance', 'notifications.json')
DISMISSED_FILE = os.path.join('instance', 'dismissed_notifications.json')

def _ensure_file():
    dirpath = os.path.dirname(NOTIFICATIONS_FILE)
    if not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    if not os.path.exists(NOTIFICATIONS_FILE):
        with open(NOTIFICATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'notifications': []}, f)

def load_notifications():
    _ensure_file()
    try:
        with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('notifications', [])
    except Exception:
        return []

def save_notifications(notifs):
    _ensure_file()
    with open(NOTIFICATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'notifications': notifs}, f, indent=2, default=str)

def add_notification(message, level='info', audience='site', teams=None, users=None, expires=None):
    notifs = load_notifications()
    notif = {
        'id': int(datetime.utcnow().timestamp() * 1000),
        'message': message,
        'level': level,  # info, important, urgent
        'audience': audience,  # site, teams, users
        'teams': teams or [],
        'users': users or [],
        'created': datetime.utcnow().isoformat(),
        'expires': expires
    }
    notifs.append(notif)
    save_notifications(notifs)
    return notif

def remove_notification(notif_id):
    notifs = load_notifications()
    new = [n for n in notifs if str(n.get('id')) != str(notif_id)]
    save_notifications(new)
    return True


def _ensure_dismissed_file():
    dirpath = os.path.dirname(DISMISSED_FILE)
    if not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    if not os.path.exists(DISMISSED_FILE):
        with open(DISMISSED_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)


def load_dismissals():
    _ensure_dismissed_file()
    try:
        with open(DISMISSED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_dismissals(data):
    _ensure_dismissed_file()
    with open(DISMISSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def dismiss_for_user(username, notif_id):
    """Record that `username` dismissed `notif_id`"""
    if not username:
        return False
    data = load_dismissals()
    user_key = str(username)
    lst = data.get(user_key, [])
    if str(notif_id) not in [str(x) for x in lst]:
        lst.append(str(notif_id))
    data[user_key] = lst
    try:
        save_dismissals(data)
        return True
    except Exception:
        return False


def get_dismissed_for_user(username):
    if not username:
        return []
    data = load_dismissals()
    return [str(x) for x in data.get(str(username), [])]
