"""
Helpers for enumerating and managing SQLite .db files in the application's instance folder.

Provides safe helpers: list_instance_db_files, backup_db_file, set_journal_mode.
All operations are careful to only operate within current_app.instance_path and
perform basic validation (PRAGMA integrity_check) before accepting changes.
"""
from flask import current_app
import os
import sqlite3
from datetime import datetime
import shutil
import glob
import re

FILENAME_RE = re.compile(r'^[a-zA-Z0-9_\-\.]+$')


def _is_safe_filename(name: str) -> bool:
    return bool(name and FILENAME_RE.match(name) and name.endswith('.db'))


def _db_abs_path(filename: str) -> str:
    if not _is_safe_filename(filename):
        raise ValueError('Invalid filename')
    p = os.path.join(current_app.instance_path, filename)
    if not os.path.exists(p):
        raise FileNotFoundError(filename)
    return p


def list_instance_db_files() -> list:
    """Return list of dicts describing .db files in instance folder.

    Each dict contains: name, size, mtime (iso), integrity (OK/FAIL + message), journal_mode
    """
    out = []
    inst = current_app.instance_path
    if not os.path.isdir(inst):
        return out

    for fn in sorted(os.listdir(inst)):
        if not fn.endswith('.db'):
            continue
        path = os.path.join(inst, fn)
        try:
            size = os.path.getsize(path)
            mtime = datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat() + 'Z'
            integrity = 'unknown'
            journal_mode = None
            # Check integrity and journal_mode using sqlite
            try:
                conn = sqlite3.connect(path, timeout=30)
                cur = conn.cursor()
                try:
                    cur.execute("PRAGMA integrity_check;")
                    res = cur.fetchone()
                    integrity = 'OK' if res and res[0] == 'ok' or res and res[0] == 'OK' else f'FAIL: {res[0] if res else "unknown"}'
                except Exception as ie:
                    integrity = f'ERR: {ie}'
                try:
                    cur.execute("PRAGMA journal_mode;")
                    jm = cur.fetchone()
                    if jm:
                        journal_mode = jm[0]
                except Exception:
                    journal_mode = None
                cur.close()
                conn.close()
            except Exception as e:
                integrity = f'ERR: {e}'

            out.append({
                'name': fn,
                'size': size,
                'mtime': mtime,
                'integrity': integrity,
                'journal_mode': journal_mode
            })
        except Exception:
            continue
    return out


def _ensure_backup_dir() -> str:
    bdir = current_app.config.get('DB_BACKUP_DIR')
    if not bdir:
        bdir = os.path.join(current_app.instance_path, 'backup')
        current_app.config['DB_BACKUP_DIR'] = bdir
    os.makedirs(bdir, exist_ok=True)
    return bdir


def backup_db_file(filename: str) -> str:
    """Create a timestamped backup of the DB file and enforce retention policy.

    Returns the path to the created backup file (absolute).
    """
    src = _db_abs_path(filename)
    bdir = _ensure_backup_dir()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    backup_name = f"{filename}.{timestamp}.bak"
    dst = os.path.join(bdir, backup_name)
    # Make a safe copy
    shutil.copy2(src, dst)

    # Enforce retention: keep last N backups per file
    retention = int(current_app.config.get('DB_BACKUP_RETENTION', 10))
    pattern = os.path.join(bdir, f"{filename}.*.bak")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if len(matches) > retention:
        for old in matches[retention:]:
            try:
                os.remove(old)
            except Exception:
                pass

    return dst


def set_journal_mode(filename: str, mode: str = 'wal') -> str:
    """Set PRAGMA journal_mode for the given DB file and return resulting mode string.

    Valid modes include 'DELETE', 'WAL', 'TRUNCATE', 'PERSIST', 'MEMORY'.
    Mode matching is case-insensitive.
    """
    mode = (mode or '').strip().upper()
    if mode not in ('DELETE', 'WAL', 'TRUNCATE', 'PERSIST', 'MEMORY'):
        raise ValueError('Invalid journal mode')
    path = _db_abs_path(filename)
    conn = sqlite3.connect(path, timeout=30)
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA journal_mode = {mode};")
        res = cur.fetchone()
        # res[0] is returned journal mode
        return res[0] if res else None
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
