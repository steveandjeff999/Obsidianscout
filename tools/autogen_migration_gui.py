"""
Tools: Autogenerate and apply Alembic migrations with a small Tk UI

This script intentionally runs only when executed directly. It will:
 - start a Tkinter GUI to choose binds and options
 - autogenerate Alembic revision(s) with `autogenerate=True`
 - optionally apply `alembic upgrade head` to the DB(s)

Notes:
 - This calls Alembic programmatically and monkeypatches the Flask-Migrate
   DB engine/metadata so the existing `migrations/env.py` (that uses
   current_app.extensions['migrate'].db) can work for each bind.
 - The script does not auto-run at server start and requires manual execution.
 - Generated migration files will be written to `migrations/versions/` as
   normal Alembic revisions. Please review and commit them before applying
   in a production environment.
"""

import os
import sys
import threading
import traceback
import shutil
import tempfile
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

try:
    from alembic.config import Config
    from alembic import command
    from alembic.util import exc as alembic_exc
except Exception as e:
    print("This script requires Alembic to be installed. Run 'pip install alembic' if needed.")
    raise

from flask import current_app


def log(msg, text_widget=None):
    msg = f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n"
    if text_widget:
        text_widget.configure(state='normal')
        text_widget.insert(tk.END, msg)
        text_widget.see(tk.END)
        text_widget.configure(state='disabled')
    else:
        print(msg)


def run_alembic_stamp(engine, revision='heads', log_widget=None):
    """Run `alembic stamp <revision>` programmatically for the given engine."""
    from app import db
    ext = current_app.extensions.get('migrate')
    if not ext:
        raise RuntimeError('Flask-Migrate extension not initialized')
    migrate_db = ext.db
    original_get_engine = getattr(migrate_db, 'get_engine', None)
    try:
        migrate_db.get_engine = lambda bind=None: engine
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cfg = Config(os.path.join(repo_root, 'migrations', 'alembic.ini'))
        cfg.set_main_option('script_location', os.path.join(repo_root, 'migrations'))
        log(f"Stamping DB at {str(engine.url)} -> {revision}", log_widget)
        command.stamp(cfg, revision)
        log(f"Stamp applied for {str(engine.url)} -> {revision}", log_widget)
        return True, None
    except alembic_exc.CommandError as ce:
        log(f"Alembic command error during stamp: {ce}", log_widget)
        return False, str(ce)
    except Exception:
        error_text = traceback.format_exc()
        log(f"Error during stamp: {error_text}", log_widget)
        return False, error_text
    finally:
        try:
            migrate_db.get_engine = original_get_engine
        except Exception:
            pass


def _extract_revision_from_error(text):
    # Try to detect migration file path or revision id in the traceback
    import re
    if not text:
        return None
    # Look for migration filename path
    m = re.search(r"migrations[\\/](?:versions|versions[\\/])(?:[^\\/]+[\\/])?([^\\/\n]+\.py)", text)
    if m:
        filename = m.group(1)
        # revision id is before first '_' or in filename
        rev = filename.split('_')[0]
        return rev, filename
    # Look for explicit revision ids (hex) in traceback
    m2 = re.search(r"([0-9a-f]{10,20})", text)
    if m2:
        return m2.group(1), None
    return None


def _categorize_upgrade_error(text):
    if not text:
        return 'unknown', 'Unknown upgrade error'
    # Duplicate column
    if 'duplicate column' in text.lower() or 'duplicate column name' in text.lower():
        return 'duplicate_column', 'Duplicate column found (column already exists). Consider stamping this revision.'
    # Unique constraint
    if 'unique constraint failed' in text.lower() or 'unique constraint' in text.lower():
        return 'unique_violation', 'Unique constraint violation during data insert. Consider deduplicating data or stamping the revision.'
    # No such table
    if 'no such table' in text.lower() or 'no such table:' in text.lower():
        return 'missing_table', 'Missing table error. A dependency migration may not have been applied.'
    # Default
    return 'unknown', 'Unexpected DB error during upgrade'


def parse_upgrade_error_details(text):
    """Parse common DB upgrade error messages to pull out table, column, value, revision.
    Returns dict: {category, table, column, value, rev, file}
    """
    details = {'category': None, 'table': None, 'column': None, 'value': None, 'rev': None, 'file': None}
    if not text:
        return details
    cat, _ = _categorize_upgrade_error(text)
    details['category'] = cat
    # Duplicate column
    import re
    m = re.search(r"duplicate column(?: name)?:\s*([0-9A-Za-z_]+)", text, re.IGNORECASE)
    if m:
        details['column'] = m.group(1)
    # No such table
    m2 = re.search(r"no such table:\s*'?([0-9A-Za-z_]+)'?", text, re.IGNORECASE)
    if m2:
        details['table'] = m2.group(1)
    # Unique constraint: table.column
    m3 = re.search(r"UNIQUE constraint failed: ([0-9A-Za-z_]+)\.([0-9A-Za-z_]+)", text, re.IGNORECASE)
    if m3:
        details['table'] = m3.group(1)
        details['column'] = m3.group(2)
    # Also try to extract the revision (from traceback or filenames)
    rev_info = _extract_revision_from_error(text)
    if rev_info:
        if isinstance(rev_info, tuple):
            details['rev'], details['file'] = rev_info
        else:
            details['rev'] = rev_info
    # If duplicate column but missing table info, try to find migration file adding this column and discover table
    if details.get('category') == 'duplicate_column' and details.get('column') and not details.get('table'):
        # Try to locate a migration adding this column
        mig_hint = details.get('file') or details.get('rev')
        rev_create, mig_path, table_name = find_migration_adding_column(details['column'], mig_path_hint=mig_hint if mig_hint else None)
        if table_name:
            details['table'] = table_name
            if not details.get('rev') and rev_create:
                details['rev'] = rev_create
            if not details.get('file') and mig_path:
                details['file'] = os.path.basename(mig_path)
    return details


def db_table_exists(engine, table_name):
    from sqlalchemy import inspect
    try:
        insp = inspect(engine)
        return table_name in insp.get_table_names()
    except Exception:
        # Fallback for sqlite PRAGMA
        try:
            with engine.connect() as conn:
                res = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                return len(list(res)) > 0
        except Exception:
            return False


def db_column_exists(engine, table_name, column_name):
    from sqlalchemy import inspect
    try:
        insp = inspect(engine)
        cols = insp.get_columns(table_name)
        return any(c['name'] == column_name for c in cols)
    except Exception:
        # For sqlite, try pragma
        try:
            with engine.connect() as conn:
                res = conn.execute(f"PRAGMA table_info('{table_name}')")
                for row in res:
                    if str(row[1]) == column_name:
                        return True
        except Exception:
            pass
        return False


def find_migration_creating_table(table_name):
    """Search migrations/versions for a revision that creates 'table_name'. Returns (rev, path) or (None, None)."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    versions_dir = os.path.join(repo_root, 'migrations', 'versions')
    if not os.path.isdir(versions_dir):
        return None, None
    for f in os.listdir(versions_dir):
        if not f.endswith('.py'):
            continue
        path = os.path.join(versions_dir, f)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                txt = fh.read()
            if (
                f"create_table('{table_name}'" in txt
                or f"create_table(\"{table_name}\"" in txt
                or f"sa.Table('{table_name}'" in txt
                or f"sa.Table(\"{table_name}\"" in txt
                or f"op.create_table('{table_name}'" in txt
                or f"op.create_table(\"{table_name}\"" in txt
            ):
                rev = f.split('_')[0]
                return rev, path
        except Exception:
            pass
    return None, None


def find_migration_referencing_table(table_name):
    """Return a list of (rev, path) migration files that reference table_name at all.
    This helps to find which migration creates or references a missing table."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    versions_dir = os.path.join(repo_root, 'migrations', 'versions')
    if not os.path.isdir(versions_dir):
        return []
    results = []
    for f in os.listdir(versions_dir):
        if not f.endswith('.py'):
            continue
        path = os.path.join(versions_dir, f)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                txt = fh.read()
            # look for create_table or batch_alter_table or sa.Table or op.batch_alter_table
            if (
                f"create_table('{table_name}'" in txt
                or f"create_table(\"{table_name}\"" in txt
                or f"sa.Table('{table_name}'" in txt
                or f"sa.Table(\"{table_name}\"" in txt
                or f"op.batch_alter_table('{table_name}'" in txt
                or f"op.batch_alter_table(\"{table_name}\"" in txt
                or f"batch_alter_table('{table_name}'" in txt
                or f"batch_alter_table(\"{table_name}\"" in txt
            ):
                rev = f.split('_')[0]
                results.append((rev, path))
        except Exception:
            continue
    return results


def find_bulk_insert_values(mig_path, table_name, column_name=None):
    """Search migration file for op.bulk_insert into table with values. Returns list of value dicts or None"""
    import ast
    try:
        with open(mig_path, 'r', encoding='utf-8') as fh:
            src = fh.read()
    except Exception:
        return None
    # Simple heuristic: look for op.bulk_insert( sa.table('tablename', ...), [ ... ] ) and extract
    hits = []
    import re
    pattern = r"op.bulk_insert\(\s*sa\.table\(\s*['\"]" + re.escape(table_name) + r"['\"].*?\),\s*(\[.*?\])\s*\)"
    m = re.search(pattern, src, re.S)
    if not m:
        return None
    list_src = m.group(1)
    try:
        # Safely eval literal via ast.literal_eval
        vals = ast.literal_eval(list_src)
        if isinstance(vals, list):
            if column_name:
                # return list of the column values
                return [v.get(column_name) for v in vals if isinstance(v, dict) and column_name in v]
            return vals
    except Exception:
        return None
    return None


def find_migration_adding_column(column_name, mig_path_hint=None):
    """Search migrations/versions for a revision that adds 'column_name'.
    If mig_path_hint is given (path to file), prioritize that file.
    Returns (rev, path, table_name) or (None, None, None)."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    versions_dir = os.path.join(repo_root, 'migrations', 'versions')
    if not os.path.isdir(versions_dir):
        return None, None, None
    search_files = []
    if mig_path_hint and os.path.exists(mig_path_hint):
        search_files.append(mig_path_hint)
    import glob
    # If mig_path_hint looks like a revision id, attempt to match it
    if mig_path_hint and isinstance(mig_path_hint, str) and len(mig_path_hint) >= 6:
        ms = glob.glob(os.path.join(versions_dir, f"{mig_path_hint}_*.py"))
        for f in ms:
            search_files.append(f)
    # include all files for scanning
    for f in os.listdir(versions_dir):
        if not f.endswith('.py'):
            continue
        path = os.path.join(versions_dir, f)
        if path not in search_files:
            search_files.append(path)
    import re
    for path in search_files:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                txt = fh.read()
            # Look for op.add_column('table', sa.Column('col' ...))
            pattern1 = re.compile(r"op\.add_column\(\s*['\"]([0-9A-Za-z_]+)['\"]\s*,\s*sa\.Column\(\s*['\"]" + re.escape(column_name) + r"['\"]", re.S)
            m1 = pattern1.search(txt)
            if m1:
                table_name = m1.group(1)
                rev = os.path.basename(path).split('_')[0]
                return rev, path, table_name
            # Look for batch_alter_table('table') + add_column or Column in batch block
            pattern2 = re.compile(r"op\.batch_alter_table\(\s*['\"]([0-9A-Za-z_]+)['\"](?:,.*?)?\)\s*as\s*[^:]+:\s*.*add_column\(.*['\"]" + re.escape(column_name) + r"['\"]", re.S)
            m2 = pattern2.search(txt)
            if m2:
                table_name = m2.group(1)
                rev = os.path.basename(path).split('_')[0]
                return rev, path, table_name
        except Exception:
            continue
    return None, None, None




def run_alembic_revision(app, engine, metadata, message_text, log_widget=None, preview_dir=None):
    """Run alembic autogenerate revision using the provided engine and metadata.
    This monkeypatches `current_app.extensions['migrate'].db` so `migrations/env.py`
    uses the provided engine and metadata during autogenerate.
    """
    from app import db
    # Save original attributes
    ext = current_app.extensions.get('migrate')
    if not ext:
        raise RuntimeError('Flask-Migrate extension not initialized')

    def run_alembic_stamp(engine, revision='heads', log_widget=None):
        """Run `alembic stamp <revision>` programmatically for the given engine."""
        from app import db
        ext = current_app.extensions.get('migrate')
        if not ext:
            raise RuntimeError('Flask-Migrate extension not initialized')
        migrate_db = ext.db
        original_get_engine = getattr(migrate_db, 'get_engine', None)
        try:
            migrate_db.get_engine = lambda bind=None: engine
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            cfg = Config(os.path.join(repo_root, 'migrations', 'alembic.ini'))
            cfg.set_main_option('script_location', os.path.join(repo_root, 'migrations'))
            log(f"Stamping DB at {str(engine.url)} -> {revision}", log_widget)
            command.stamp(cfg, revision)
            log(f"Stamp applied for {str(engine.url)} -> {revision}", log_widget)
            return True, None
        except alembic_exc.CommandError as ce:
            log(f"Alembic command error during stamp: {ce}", log_widget)
            return False, str(ce)
        except Exception:
            error_text = traceback.format_exc()
            log(f"Error during stamp: {error_text}", log_widget)
            return False, error_text
        finally:
            try:
                migrate_db.get_engine = original_get_engine
            except Exception:
                pass

    def _extract_revision_from_error(text):
        # Try to detect migration file path or revision id in the traceback
        import re
        if not text:
            return None
        # Look for migration filename path
        m = re.search(r"migrations[\\/](?:versions|versions[\\/])(?:[^\\/]+[\\/])?([^\\/\n]+\.py)", text)
        if m:
            filename = m.group(1)
            # revision id is before first '_' or in filename
            rev = filename.split('_')[0]
            return rev, filename
        # Look for explicit revision ids (hex) in traceback
        m2 = re.search(r"([0-9a-f]{10,20})", text)
        if m2:
            return m2.group(1), None
        return None
    migrate_db = ext.db
    original_get_engine = getattr(migrate_db, 'get_engine', None)
    original_metadatas = getattr(migrate_db, 'metadatas', {}).copy()

    # Helper to temporarily swap get_engine to return our target engine
    def patched_get_engine(bind=None):
        return engine

    # Replace metadata mapping so env.py's get_metadata returns the bind metadata
    try:
        # Do not set migrate_db.engine (read-only); override get_engine to return our engine
        migrate_db.get_engine = patched_get_engine
        # For autogeneration, we swap the default metadata mapping to the bind-specific metadata
        if hasattr(migrate_db, 'metadatas') and metadata is not None:
            migrate_db.metadatas[None] = metadata

        # Run alembic revision autogeneration
        # Repo root (tools/.. = project root)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cfg = Config(os.path.join(repo_root, 'migrations', 'alembic.ini'))
        # Check whether DB is at script head (no unapplied migrations)
        try:
            from alembic.script import ScriptDirectory
            from alembic.runtime.migration import MigrationContext
            script_dir = ScriptDirectory.from_config(cfg)
            script_heads = set(script_dir.get_heads() or [])
            # Use engine.connect to get DB current revision
            with engine.connect() as conn:
                mc = MigrationContext.configure(conn)
                db_rev = mc.get_current_revision()
            if db_rev not in script_heads:
                head_str = ','.join(script_heads) if script_heads else '(no heads)'
                # Attempt to compute list of pending revisions for helpful diagnostics
                pending = []
                try:
                    if db_rev is None:
                        pending = [r.revision for r in script_dir.walk_revisions()]
                    else:
                        for h in script_heads:
                            try:
                                for rev in script_dir.iterate_revisions(h, db_rev):
                                    pending.append(rev.revision)
                            except Exception:
                                pass
                except Exception:
                    pending = []
                pending_str = ', '.join(sorted(set(pending))) if pending else '(all revisions)'
                pending_count = len(set(pending)) if pending else 'all'
                msg = (
                    f"Target DB revision ({db_rev}) does not match migration head(s) {head_str}.\n"
                    f"Pending revisions {pending_count}: {pending_str}.\n"
                    "The database has unapplied migrations. Run 'alembic upgrade head' or enable Apply in the GUI."
                )
                log(msg, log_widget)
                return None, msg
        except Exception:
            # If this check fails for any reason, continue to autogenerate (we'll handle errors below)
            pass
        # If preview_dir is provided, set script_location to that temporary folder
        if preview_dir:
            os.makedirs(os.path.join(preview_dir, 'versions'), exist_ok=True)
            cfg.set_main_option('script_location', preview_dir)
            # Ensure preview env.py and alembic.ini exist (copy from repo migrations)
            try:
                migrations_src = os.path.join(repo_root, 'migrations')
                env_src = os.path.join(migrations_src, 'env.py')
                env_dst = os.path.join(preview_dir, 'env.py')
                if os.path.exists(env_src) and not os.path.exists(env_dst):
                    shutil.copy2(env_src, env_dst)
                ini_src = os.path.join(migrations_src, 'alembic.ini')
                ini_dst = os.path.join(preview_dir, 'alembic.ini')
                if os.path.exists(ini_src) and not os.path.exists(ini_dst):
                    shutil.copy2(ini_src, ini_dst)
            except Exception as e:
                log(f"Warning: unable to ensure preview env files: {e}", log_widget)
            # Log to help debug: check env.py presence and directory
            try:
                listing = os.listdir(preview_dir)
                env_ok = os.path.exists(os.path.join(preview_dir, 'env.py'))
                log(f"Preview dir listing: {listing} | env.py present: {env_ok}", log_widget)
            except Exception:
                pass
        else:
            cfg.set_main_option('script_location', os.path.join(repo_root, 'migrations'))
        log(f"Generating revision (autogenerate) for engine {str(engine.url)}", log_widget)
        command.revision(cfg, autogenerate=True, message=message_text)
        # If preview_dir set, find generated file
        if preview_dir:
            versions_dir = os.path.join(preview_dir, 'versions')
            files = [os.path.join(versions_dir, f) for f in os.listdir(versions_dir) if f.endswith('.py')]
            if not files:
                return None, 'No migration file generated (no schema changes detected).'
            latest = max(files, key=os.path.getctime)
            return latest, None

        log(f"Autogenerate complete for engine: {str(engine.url)}", log_widget)
        # Non-preview mode; autogenerate written to repo migrations folder
        return None, None

    except alembic_exc.CommandError as ce:
        # Common: 'Target database is not up to date.' when there are unapplied migrations
        msg = (f"Alembic CommandError during autogenerate: {ce}.\n"
               f"This usually means the target DB has unapplied migrations; run 'alembic upgrade head' or enable Apply in the GUI.")
        log(msg, log_widget)
        # Return a message for preview UI to display instead of 'no migration generated'
        return None, msg
    except Exception:
        error_text = traceback.format_exc()
        log(f"Error during autogenerate: {error_text}", log_widget)
        raise
    finally:
        # Restore original attributes; do not try to set read-only 'engine'
        try:
            migrate_db.get_engine = original_get_engine
            migrate_db.metadatas = original_metadatas
        except Exception:
            pass


def run_alembic_upgrade(engine, log_widget=None):
    """Run `alembic upgrade head` for the given engine/URL.
    Uses the same env.py behavior (it will pick up engine via migrate ext)."""
    from app import db
    ext = current_app.extensions.get('migrate')
    if not ext:
        raise RuntimeError('Flask-Migrate extension not initialized')
    migrate_db = ext.db
    original_get_engine = getattr(migrate_db, 'get_engine', None)
    try:
        # Do not set migrate_db.engine here (it's read-only); override get_engine instead
        migrate_db.get_engine = lambda bind=None: engine
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cfg = Config(os.path.join(repo_root, 'migrations', 'alembic.ini'))
        cfg.set_main_option('script_location', os.path.join(repo_root, 'migrations'))
        # Detect multiple heads and choose target accordingly
        try:
            from alembic.script import ScriptDirectory
            script_dir = ScriptDirectory.from_config(cfg)
            script_heads = list(script_dir.get_heads() or [])
        except Exception:
            script_heads = []
        if len(script_heads) > 1:
            log(f"Multiple Alembic heads detected: {', '.join(script_heads)}. Upgrading all heads ('heads').", log_widget)
            target = 'heads'
        else:
            target = 'head'
        log(f"Upgrading DB at {str(engine.url)} -> {target}", log_widget)
        command.upgrade(cfg, target)
        log(f"Upgrade applied for {str(engine.url)} -> {target}", log_widget)
        return True, None, None, None
    except alembic_exc.CommandError as ce:
        # Handle specific alembic command errors like MultipleHeads gracefully
        log(f"Alembic command error during upgrade: {ce}. You may need to run 'alembic merge' to merge branches or run 'alembic upgrade heads' to apply all heads.", log_widget)
        cat, msg = _categorize_upgrade_error(str(ce))
        rev_info = _extract_revision_from_error(str(ce))
        return False, str(ce), cat, rev_info
    except Exception as e:
        error_text = traceback.format_exc()
        log(f"Error during upgrade: {error_text}", log_widget)
        cat, _ = _categorize_upgrade_error(str(e))
        rev_info = _extract_revision_from_error(str(e))
        return False, error_text, cat, rev_info
    finally:
        try:
            migrate_db.get_engine = original_get_engine
        except Exception:
            pass
    return False, "Unknown error", 'unknown', None


def build_gui():
    # Lazy-import Flask app so Tk can render quickly
    try:
        # Insert repo root into path so app import works from tools/ folder
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from app import create_app, db
        app = create_app()
    except Exception as e:
        raise RuntimeError("Failed to import the Flask app. Run this from the project root or check PYTHONPATH")

    root = tk.Tk()
    root.title('DB Autogen & Migrate')
    # Main frame
    frm = ttk.Frame(root, padding=10)
    frm.grid(row=0, column=0, sticky='nsew')

    # Migration message
    ttk.Label(frm, text='Migration message:').grid(column=0, row=0, sticky='w')
    msg_entry = ttk.Entry(frm, width=80)
    msg_entry.insert(0, 'autogen: schema update')
    msg_entry.grid(column=0, row=1, sticky='w')

    # Binds list (default + SQLALCHEMY_BINDS)
    binds = {'default': app.config.get('SQLALCHEMY_DATABASE_URI')}
    binds.update(app.config.get('SQLALCHEMY_BINDS') or {})
    ttk.Label(frm, text='Select binds to autogenerate:').grid(column=0, row=2, sticky='w')
    bind_vars = {}
    row = 3
    for name, uri in binds.items():
        var = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(frm, text=f"{name} ({uri})", variable=var)
        chk.grid(column=0, row=row, sticky='w')
        bind_vars[name] = var
        row += 1

    # Options
    preview_var = tk.BooleanVar(value=True)
    apply_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text='Preview only (no upgrade)', variable=preview_var).grid(column=0, row=row, sticky='w')
    row += 1
    ttk.Checkbutton(frm, text='Apply upgrade after generating migrations', variable=apply_var).grid(column=0, row=row, sticky='w')
    row += 1

    log_widget = scrolledtext.ScrolledText(frm, width=120, height=20, state='disabled')
    log_widget.grid(column=0, row=row, pady=10)
    row += 1

    # Helper to post messagebox calls to the main thread and wait for result
    import threading as _threading
    def _call_in_main_thread(func, *args, **kwargs):
        ev = _threading.Event()
        out = {}
        def _runner():
            try:
                out['res'] = func(*args, **kwargs)
            except Exception as e:
                out['err'] = e
            finally:
                ev.set()
        root.after(0, _runner)
        ev.wait()
        if 'err' in out:
            raise out['err']
        return out.get('res')

    def mt_showinfo(title, msg):
        return _call_in_main_thread(messagebox.showinfo, title, msg)
    def mt_showerror(title, msg):
        return _call_in_main_thread(messagebox.showerror, title, msg)
    def mt_showwarning(title, msg):
        return _call_in_main_thread(messagebox.showwarning, title, msg)
    def mt_askyesno(title, msg):
        return _call_in_main_thread(messagebox.askyesno, title, msg)

    def on_run():
        # Run in a separate thread to avoid freezing the UI
        def worker():
            try:
                with app.app_context():
                    message_text = msg_entry.get().strip() or 'autogen: schema update'
                    # Process each bind selected
                    def _get_engine_for_bind(bind_name):
                        # Prefer new-style attributes (db.engine, db.engines)
                        if bind_name == 'default':
                            if hasattr(db, 'engine') and db.engine is not None:
                                return db.engine
                        else:
                            if hasattr(db, 'engines') and isinstance(db.engines, dict):
                                eng = db.engines.get(bind_name)
                                if eng:
                                    return eng
                        # Fallback to get_engine (may be deprecated)
                        try:
                            if hasattr(db, 'get_engine'):
                                return db.get_engine(app) if bind_name == 'default' else db.get_engine(app, bind=bind_name)
                        except Exception:
                            pass
                        return None
                    for bind_name, enabled in bind_vars.items():
                        if not enabled.get():
                            continue
                        engine = _get_engine_for_bind(bind_name)
                        if bind_name == 'default':
                            metadata = db.metadatas.get(None)
                        else:
                            metadata = db.metadatas.get(bind_name)

                        if not engine:
                            log(f"No engine for bind {bind_name}; skipping", log_widget)
                            continue

                        log(f"Starting autogenerate for bind {bind_name} -> {engine.url}", log_widget)
                        # If preview only, write to a temporary directory and show content
                        gen_file = None
                        if preview_var.get():
                            tmpdir = tempfile.mkdtemp(prefix=f'alembic_preview_{bind_name}_')
                            versions_tmp = os.path.join(tmpdir, 'versions')
                            os.makedirs(versions_tmp, exist_ok=True)
                            try:
                                # Ensure preview dir has a working migrations env (copy files from main migrations)
                                # Migrations folder is at repo root, not app root
                                migrations_src = os.path.join(repo_root, 'migrations')
                                if os.path.exists(migrations_src):
                                    try:
                                        for item in os.listdir(migrations_src):
                                            s = os.path.join(migrations_src, item)
                                            d = os.path.join(tmpdir, item)
                                            if os.path.isdir(s):
                                                shutil.copytree(s, d, dirs_exist_ok=True)
                                            else:
                                                shutil.copy2(s, d)
                                    except Exception as copy_e:
                                        log(f"Warning: could not copy migrations into preview: {copy_e}", log_widget)
                                # Ensure env.py and alembic.ini are present in preview; copy if missing
                                env_src = os.path.join(migrations_src, 'env.py')
                                env_dst = os.path.join(tmpdir, 'env.py')
                                if os.path.exists(env_src) and not os.path.exists(env_dst):
                                    try:
                                        shutil.copy2(env_src, env_dst)
                                    except Exception as e:
                                        log(f"Warning: could not copy env.py into preview: {e}", log_widget)
                                ini_src = os.path.join(migrations_src, 'alembic.ini')
                                ini_dst = os.path.join(tmpdir, 'alembic.ini')
                                if os.path.exists(ini_src) and not os.path.exists(ini_dst):
                                    try:
                                        shutil.copy2(ini_src, ini_dst)
                                    except Exception as e:
                                        log(f"Warning: could not copy alembic.ini into preview: {e}", log_widget)
                                # Log preview contents for debugging
                                try:
                                    preview_listing = os.listdir(tmpdir)
                                    log(f"Preview directory contents: {preview_listing}", log_widget)
                                except Exception as e:
                                    log(f"Warning: could not list preview dir contents: {e}", log_widget)
                                result = run_alembic_revision(app, engine, metadata, f"{message_text} [{bind_name}]", log_widget, preview_dir=tmpdir)
                                if isinstance(result, tuple):
                                    gen_file, info_msg = result
                                else:
                                    gen_file, info_msg = result, None
                                if info_msg:
                                    content = info_msg
                                elif gen_file:
                                    with open(gen_file, 'r', encoding='utf-8') as f:
                                        content = f.read()
                                else:
                                    content = 'No migration file generated (no schema changes detected).'

                                # Show preview popup
                                def show_preview(content=content, gen_file=gen_file, tmpdir=tmpdir, bind_name=bind_name):
                                    pre_win = tk.Toplevel(root)
                                    pre_win.title(f'Preview: {bind_name}')
                                    txt = scrolledtext.ScrolledText(pre_win, width=120, height=40)
                                    txt.pack(fill='both', expand=True)
                                    txt.insert(tk.END, content)
                                    txt.configure(state='disabled')

                                    def on_apply():
                                        # Move generated file to real migrations directory and (optionally) upgrade
                                        if gen_file:
                                            dest_dir = os.path.join(app.root_path, 'migrations', 'versions')
                                            os.makedirs(dest_dir, exist_ok=True)
                                            dest_file = os.path.join(dest_dir, os.path.basename(gen_file))
                                            try:
                                                shutil.copy(gen_file, dest_file)
                                                log(f'Copied preview migration to {dest_file}', log_widget)
                                                if apply_var.get():
                                                    # Ensure upgrades run inside app context
                                                    try:
                                                        with app.app_context():
                                                            success, err, cat, rev_info = run_alembic_upgrade(engine, log_widget)
                                                            if success:
                                                                log(f'Upgrade completed for {bind_name}', log_widget)
                                                            else:
                                                                log(f'Upgrade did not complete successfully for {bind_name}: {err}', log_widget)
                                                    except Exception as e:
                                                        log(f'Error applying upgrade in app context: {e}\n{traceback.format_exc()}', log_widget)
                                                    mt_showinfo('Applied', f'Migration applied for bind {bind_name}')
                                            except Exception as e:
                                                log(f'Error copying/applying migration: {e}\n{traceback.format_exc()}', log_widget)
                                                mt_showerror('Error', str(e))
                                        else:
                                            # No migration generated; if info_msg indicates the DB is behind and the user requested Apply,
                                            # run Alembic upgrade anyway.
                                            if apply_var.get() and isinstance(info_msg, str) and ('unapplied migrations' in info_msg or 'does not match migration head' in info_msg):
                                                try:
                                                        with app.app_context():
                                                            success, err, cat, rev_info = run_alembic_upgrade(engine, log_widget)
                                                        if success:
                                                            mt_showinfo('Applied', f'Upgrade applied for bind {bind_name}')
                                                        else:
                                                            cat_msg = _categorize_upgrade_error(err)[1]
                                                            mt_showerror('Error', f'Upgrade failed for bind {bind_name}: {err}\n\n{cat_msg}')
                                                            # Offer to view / stamp / resolve failing migration automatically
                                                            details = parse_upgrade_error_details(str(err))
                                                            rev_info = details.get('rev') or _extract_revision_from_error(err)
                                                            failed_rev = rev_info[0] if isinstance(rev_info, tuple) else rev_info
                                                            failed_file = details.get('file')
                                                            # Duplicate column: check if exists and offer stamping
                                                            if details.get('category') == 'duplicate_column' and details.get('table') and details.get('column'):
                                                                log(f"Detected duplicate column {details['column']} on table {details['table']} (preview).", log_widget)
                                                                try:
                                                                    exists = db_column_exists(engine, details['table'], details['column'])
                                                                except Exception:
                                                                    exists = False
                                                                # Determine failed_rev: prefer rev_info->details->scan migration file
                                                                if not failed_rev:
                                                                    # try details rev
                                                                    failed_rev = details.get('rev')
                                                                if not failed_rev:
                                                                    rev_create, mig_path, tbl = find_migration_adding_column(details['column'], mig_path_hint=details.get('file') or details.get('rev'))
                                                                    if rev_create:
                                                                        failed_rev = rev_create
                                                                if exists and failed_rev:
                                                                    if mt_askyesno('Stamp?', f"Column {details['column']} already exists on {details['table']}. Stamp revision {failed_rev} to mark as applied?"):
                                                                        try:
                                                                            with app.app_context():
                                                                                stamped, stamp_err = run_alembic_stamp(engine, failed_rev, log_widget)
                                                                                if stamped:
                                                                                    mt_showinfo('Stamped', f'Stamped {failed_rev} for bind {bind_name} successfully')
                                                                                    # retry
                                                                                    with app.app_context():
                                                                                        success2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                                                        if success2:
                                                                                            mt_showinfo('Upgrade', f'Upgrade completed for bind {bind_name} after stamping')
                                                                                        else:
                                                                                            mt_showerror('Upgrade failed', f'Upgrade still failed after stamping: {err2}')
                                                                                else:
                                                                                    mt_showerror('Stamp failed', f'Failed to stamp {failed_rev}: {stamp_err}')
                                                                        except Exception as e:
                                                                            log(f'Error stamping migration: {e}\n{traceback.format_exc()}', log_widget)
                                                                            mt_showerror('Error', str(e))
                                                            # Unique violation: offer to delete duplicates and retry
                                                            elif details.get('category') == 'unique_violation' and details.get('table') and details.get('column'):
                                                                # Try to extract the offending values from migration file using rev_info file or details['file']
                                                                mig_path = None
                                                                if details.get('file'):
                                                                    mig_path = os.path.join(repo_root, 'migrations', 'versions', details['file'])
                                                                elif failed_rev:
                                                                    # attempt wildcard match
                                                                    import glob
                                                                    ms = glob.glob(os.path.join(repo_root, 'migrations', 'versions', f"{failed_rev}_*.py"))
                                                                    if ms:
                                                                        mig_path = ms[0]
                                                                vals = None
                                                                if mig_path and os.path.exists(mig_path):
                                                                    vals = find_bulk_insert_values(mig_path, details['table'], details['column'])
                                                                # If we found values, ask to delete duplicates
                                                                if vals:
                                                                    if mt_askyesno('Delete duplicates?', f'Unique constraint on {details["table"]}.{details["column"]} failed for values {vals}. Delete existing duplicates in DB and retry?'):
                                                                        # Perform deletion
                                                                        try:
                                                                            from sqlalchemy import text
                                                                            # Validate identifiers (basic)
                                                                            import re
                                                                            def _safe_ident(name):
                                                                                return re.match(r'^[A-Za-z0-9_]+$', name) is not None
                                                                            tname = details['table']
                                                                            cname = details['column']
                                                                            if not (_safe_ident(tname) and _safe_ident(cname)):
                                                                                raise ValueError('Unsafe table/column name detected')
                                                                            with engine.begin() as conn:
                                                                                for v in vals:
                                                                                    conn.execute(text(f"DELETE FROM {tname} WHERE {cname} = :val"), {'val': v})
                                                                            mt_showinfo('Deleted', f'Deleted duplicates; retrying upgrade')
                                                                            with app.app_context():
                                                                                success2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                                                if success2:
                                                                                    mt_showinfo('Upgrade', f'Upgrade completed for bind {bind_name} after dedup')
                                                                                else:
                                                                                    mt_showerror('Upgrade failed', f'Upgrade still failed after dedup: {err2}')
                                                                        except Exception as e:
                                                                            log(f'Error deleting duplicates: {e}\n{traceback.format_exc()}', log_widget)
                                                                            mt_showerror('Error', str(e))
                                                                else:
                                                                    if mt_askyesno('Conflict', f'Unique constraint failed for {details["table"]}.{details["column"]}. Would you like to stamp this revision ({failed_rev}) to skip it?') and failed_rev:
                                                                        try:
                                                                            with app.app_context():
                                                                                stamped, stamp_err = run_alembic_stamp(engine, failed_rev, log_widget)
                                                                                if stamped:
                                                                                    mt_showinfo('Stamped', f'Stamped {failed_rev} for bind {bind_name} successfully')
                                                                                else:
                                                                                    mt_showerror('Stamp failed', f'Failed to stamp {failed_rev}: {stamp_err}')
                                                                        except Exception as e:
                                                                            log(f'Error stamping migration: {e}\n{traceback.format_exc()}', log_widget)
                                                                            mt_showerror('Error', str(e))
                                                            # Missing table: attempt to find creating migration or offer to stamp
                                                            elif details.get('category') == 'missing_table' and details.get('table'):
                                                                log(f"Detected missing table {details['table']} during preview apply.", log_widget)
                                                                rev_create, mig_path = find_migration_creating_table(details['table'])
                                                                if rev_create and os.path.exists(mig_path):
                                                                    if mt_askyesno('Missing table', f"Found migration {os.path.basename(mig_path)} creating table {details['table']}. Stamp it to mark as applied and continue? (Only use if you know the schema exists)"):
                                                                        try:
                                                                            with app.app_context():
                                                                                stamped, stamp_err = run_alembic_stamp(engine, rev_create, log_widget)
                                                                                if stamped:
                                                                                    mt_showinfo('Stamped', f'Stamped {rev_create} as applied')
                                                                                    with app.app_context():
                                                                                        success2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                                                        if success2:
                                                                                            mt_showinfo('Upgrade', f'Upgrade completed for bind {bind_name} after stamping creation rev')
                                                                                        else:
                                                                                            mt_showerror('Upgrade failed', f'Upgrade still failed after stamping creation rev: {err2}')
                                                                                else:
                                                                                    mt_showerror('Stamp failed', f'Failed to stamp creation rev {rev_create}: {stamp_err}')
                                                                        except Exception as e:
                                                                            log(f'Error stamping migration: {e}\n{traceback.format_exc()}', log_widget)
                                                                            mt_showerror('Error', str(e))
                                                                else:
                                                                    candidates = find_migration_referencing_table(details['table'])
                                                                    if candidates:
                                                                        # suggest the first candidate
                                                                        cand_rev, cand_path = candidates[0]
                                                                        if mt_askyesno('Missing table', f"Found migration {os.path.basename(cand_path)} referencing table {details['table']}. Stamp it to mark as applied and continue? (Only do this if you know the schema exists.)"):
                                                                            try:
                                                                                with app.app_context():
                                                                                    stamped, stamp_err = run_alembic_stamp(engine, cand_rev, log_widget)
                                                                                    if stamped:
                                                                                        mt_showinfo('Stamped', f'Stamped {cand_rev} as applied')
                                                                                        with app.app_context():
                                                                                            success2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                                                            if success2:
                                                                                                mt_showinfo('Upgrade', f'Upgrade completed for bind {bind_name} after stamping creation rev')
                                                                                            else:
                                                                                                mt_showerror('Upgrade failed', f'Upgrade still failed after stamping creation rev: {err2}')
                                                                                    else:
                                                                                        mt_showerror('Stamp failed', f'Failed to stamp creation rev {cand_rev}: {stamp_err}')
                                                                            except Exception as e:
                                                                                log(f'Error stamping migration: {e}\n{traceback.format_exc()}', log_widget)
                                                                                mt_showerror('Error', str(e))
                                                                    else:
                                                                        mt_showinfo('Missing table', f"No migration found creating table {details['table']}. You may need to apply migrations in order or merge heads.")
                                                            else:
                                                                # Fallback: offer to view/stamp the failing migration
                                                                if failed_rev:
                                                                    if mt_askyesno('Stamp?', f'Failed revision {failed_rev} detected. Stamp this revision and continue?'):
                                                                        try:
                                                                            with app.app_context():
                                                                                stamped, stamp_err = run_alembic_stamp(engine, failed_rev, log_widget)
                                                                                if stamped:
                                                                                    mt_showinfo('Stamped', f'Stamped {failed_rev} for bind {bind_name} successfully')
                                                                                else:
                                                                                    mt_showerror('Stamp failed', f'Failed to stamp {failed_rev}: {stamp_err}')
                                                                        except Exception as e:
                                                                            log(f'Error stamping migration: {e}\n{traceback.format_exc()}', log_widget)
                                                                            mt_showerror('Error', str(e))
                                                except Exception as e:
                                                    log(f'Error applying upgrade in app context (no gen file): {e}\n{traceback.format_exc()}', log_widget)
                                                    mt_showerror('Error', str(e))
                                            else:
                                                mt_showinfo('Nothing to apply', 'No migration file to apply')

                                    def on_discard():
                                        try:
                                            shutil.rmtree(tmpdir)
                                        except Exception:
                                            pass
                                        pre_win.destroy()

                                    btn_frame = ttk.Frame(pre_win)
                                    btn_frame.pack(fill='x')
                                    ttk.Button(btn_frame, text='Apply', command=on_apply).pack(side='left')
                                    # Offer Stamp option when info_msg indicates unapplied migrations
                                    def on_stamp():
                                        if mt_askyesno('Stamp confirmation', f'STAMP MOVES alembic revision mark(s) for bind {bind_name} to heads. This does not alter schema but marks migrations as applied. Confirm?'):
                                            try:
                                                with app.app_context():
                                                    stamped, stamp_err = run_alembic_stamp(engine, 'heads', log_widget)
                                                    if stamped:
                                                        mt_showinfo('Stamped', f'Stamped {bind_name} to heads successfully')
                                                        log(f'Stamped {bind_name} to heads', log_widget)
                                                    else:
                                                        mt_showerror('Stamp failed', f'Failed to stamp {bind_name}: {stamp_err}')
                                                        log(f'Stamp failed for {bind_name}: {stamp_err}', log_widget)
                                            except Exception as e:
                                                log(f'Error stamping migration: {e}\n{traceback.format_exc()}', log_widget)
                                                mt_showerror('Error', str(e))
                                    # Add Stamp button only if info_msg indicates unapplied migrations
                                    if info_msg and ('unapplied migrations' in info_msg or 'does not match migration head' in info_msg):
                                        ttk.Button(btn_frame, text='Stamp', command=on_stamp).pack(side='left')
                                    ttk.Button(btn_frame, text='Discard', command=on_discard).pack(side='right')

                                # Show in main thread
                                root.after(0, lambda c=content, g=gen_file, t=tmpdir, b=bind_name: show_preview(c, g, t, b))
                            except Exception as e:
                                log(f'Error generating preview: {e}', log_widget)
                                try:
                                    shutil.rmtree(tmpdir)
                                except Exception:
                                    pass
                        else:
                            # Regular generation to migrations folder
                            result = run_alembic_revision(app, engine, metadata, f"{message_text} [{bind_name}]", log_widget)
                            if isinstance(result, tuple):
                                _, info_msg = result
                                if info_msg:
                                    log(f"Autogenerate info: {info_msg}", log_widget)
                        # Optionally upgrade
                        if apply_var.get() and not preview_var.get():
                            success, err, cat, rev_info = run_alembic_upgrade(engine, log_widget)
                            if success:
                                log(f'Upgrade applied for bind {bind_name}', log_widget)
                            else:
                                log(f'Upgrade failed for bind {bind_name}: {err}', log_widget)
                                details = parse_upgrade_error_details(str(err))
                                # Duplicate column
                                if details.get('category') == 'duplicate_column' and details.get('table') and details.get('column'):
                                    log(f"Detected duplicate column {details['column']} on table {details['table']}.", log_widget)
                                    try:
                                        exists = db_column_exists(engine, details['table'], details['column'])
                                    except Exception:
                                        exists = False
                                    failed_rev = None
                                    if rev_info:
                                        failed_rev = rev_info[0] if isinstance(rev_info, tuple) else rev_info
                                    if not failed_rev:
                                        # try details rev or scan files
                                        failed_rev = details.get('rev')
                                    if not failed_rev:
                                        rev_create, mig_path, tbl = find_migration_adding_column(details['column'], mig_path_hint=details.get('file') or details.get('rev'))
                                        if rev_create:
                                            failed_rev = rev_create
                                    if exists and failed_rev:
                                        # Ask the user whether to stamp this revision
                                        resp = mt_askyesno('Stamp?', f"Column {details['column']} already exists on {details['table']}. Stamp revision {failed_rev} to mark as applied?")
                                        if resp:
                                            with app.app_context():
                                                stamped, stamp_err = run_alembic_stamp(engine, failed_rev, log_widget)
                                                if stamped:
                                                    log(f'Stamped {failed_rev} for bind {bind_name}', log_widget)
                                                    # retry
                                                    succ2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                    if succ2:
                                                        log(f'Upgrade completed for bind {bind_name} after stamping', log_widget)
                                                    else:
                                                        log(f'Upgrade still failed for bind {bind_name} after stamping: {err2}', log_widget)
                                                else:
                                                    log(f'Stamp failed for {failed_rev}: {stamp_err}', log_widget)
                                # Unique violation
                                elif details.get('category') == 'unique_violation' and details.get('table') and details.get('column'):
                                    # Try to locate migration file and offending values
                                    mig_path = None
                                    if details.get('file'):
                                        mig_path = os.path.join(repo_root, 'migrations', 'versions', details['file'])
                                    elif rev_info:
                                        import glob
                                        rev_str = rev_info[0] if isinstance(rev_info, tuple) else rev_info
                                        ms = glob.glob(os.path.join(repo_root, 'migrations', 'versions', f"{rev_str}_*.py"))
                                        if ms:
                                            mig_path = ms[0]
                                    values = None
                                    if mig_path and os.path.exists(mig_path):
                                        values = find_bulk_insert_values(mig_path, details['table'], details['column'])
                                    if values:
                                        choice = mt_askyesno('Delete duplicates?', f'Unique constraint on {details["table"]}.{details["column"]} failed for values {values}. Delete existing duplicates in DB and retry?')
                                        if choice:
                                            try:
                                                from sqlalchemy import text
                                                import re
                                                def _safe_ident(name):
                                                    return re.match(r'^[A-Za-z0-9_]+$', name) is not None
                                                tname = details['table']
                                                cname = details['column']
                                                if not (_safe_ident(tname) and _safe_ident(cname)):
                                                    raise ValueError('Unsafe table/column name detected')
                                                with engine.begin() as conn:
                                                    for v in values:
                                                        conn.execute(text(f"DELETE FROM {tname} WHERE {cname} = :val"), {'val': v})
                                                log(f"Deleted duplicates for {details['table']}.{details['column']} values {values}", log_widget)
                                                # retry
                                                succ2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                if succ2:
                                                    log(f'Upgrade completed for bind {bind_name} after dedup', log_widget)
                                                else:
                                                    log(f'Upgrade still failed for bind {bind_name} after dedup: {err2}', log_widget)
                                            except Exception as e:
                                                log(f'Error deleting duplicates: {e}\n{traceback.format_exc()}', log_widget)
                                    else:
                                        # Offer to stamp revision
                                        resp = mt_askyesno('Stamp?', f'Unique constraint failed for {details["table"]}.{details["column"]}. Stamp revision {rev_str} to skip it?')
                                        if resp:
                                            with app.app_context():
                                                stamped, stamp_err = run_alembic_stamp(engine, rev_str, log_widget)
                                                if stamped:
                                                    log(f'Stamped {rev_str} for bind {bind_name}', log_widget)
                                                    succ2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                    if succ2:
                                                        log(f'Upgrade completed for bind {bind_name} after stamping', log_widget)
                                                    else:
                                                        log(f'Upgrade still failed for bind {bind_name} after stamping: {err2}', log_widget)
                                                else:
                                                    log(f'Stamp failed for {rev_str}: {stamp_err}', log_widget)
                                # Missing table
                                elif details.get('category') == 'missing_table' and details.get('table'):
                                    log(f"Detected missing table {details['table']}.", log_widget)
                                    rev_create, mig_path = find_migration_creating_table(details['table'])
                                    if rev_create:
                                        resp = mt_askyesno('Stamp creation rev?', f'Found migration {os.path.basename(mig_path)} creating {details["table"]}. Stamp it to mark as applied?')
                                        if resp:
                                            with app.app_context():
                                                stamped, stamp_err = run_alembic_stamp(engine, rev_create, log_widget)
                                                if stamped:
                                                    log(f'Stamped creation revision {rev_create} for bind {bind_name}', log_widget)
                                                    succ2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                    if succ2:
                                                        log(f'Upgrade completed for bind {bind_name} after stamping creation rev', log_widget)
                                                    else:
                                                        log(f'Upgrade still failed for bind {bind_name} after stamping creation rev: {err2}', log_widget)
                                                else:
                                                    log(f'Stamp failed for creation rev {rev_create}: {stamp_err}', log_widget)
                                    else:
                                        candidates = find_migration_referencing_table(details['table'])
                                        if candidates:
                                            cand_rev, cand_path = candidates[0]
                                            resp = mt_askyesno('Stamp creation rev?', f'Found migration {os.path.basename(cand_path)} referencing {details["table"]}. Stamp it to mark as applied?')
                                            if resp:
                                                with app.app_context():
                                                    stamped, stamp_err = run_alembic_stamp(engine, cand_rev, log_widget)
                                                    if stamped:
                                                        log(f'Stamped creation revision {cand_rev} for bind {bind_name}', log_widget)
                                                        succ2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                        if succ2:
                                                            log(f'Upgrade completed for bind {bind_name} after stamping creation rev', log_widget)
                                                        else:
                                                            log(f'Upgrade still failed for bind {bind_name} after stamping creation rev: {err2}', log_widget)
                                                    else:
                                                        log(f'Stamp failed for creation rev {cand_rev}: {stamp_err}', log_widget)
                                        else:
                                            mt_showinfo('Missing table', f"No migration found creating table {details['table']}. You may need to apply migrations in order or merge heads.")

                                    # Offer to stamp the failing revision and retry when safe
                                try:
                                    cat_msg = _categorize_upgrade_error(err)[1] if err else ''
                                except Exception:
                                    cat_msg = ''
                                # Only offer stamping for likely-safe errors (not missing table or unknown)
                                if cat not in ('missing_table', 'unknown') and rev_info:
                                    failed_rev = rev_info[0] if isinstance(rev_info, tuple) else rev_info
                                    if failed_rev:
                                        # Ask the user on the main thread
                                        stamp_result = mt_askyesno('Stamp?', f'Upgrade failed for {bind_name}: {cat_msg}\n\nFailed revision {failed_rev} detected. Stamp this revision and retry?')
                                        if stamp_result:
                                            try:
                                                with app.app_context():
                                                    stamped, stamp_err = run_alembic_stamp(engine, failed_rev, log_widget)
                                                    if stamped:
                                                        log(f'Stamped {failed_rev} for bind {bind_name}', log_widget)
                                                        # Retry upgrade
                                                        succ2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget)
                                                        if succ2:
                                                            log(f'Upgrade completed for bind {bind_name} after stamping', log_widget)
                                                        else:
                                                            log(f'Upgrade still failed for bind {bind_name} after stamping: {err2}', log_widget)
                                                    else:
                                                        log(f'Stamp failed for {failed_rev}: {stamp_err}', log_widget)
                                            except Exception as e:
                                                log(f'Error stamping migration for {bind_name}: {e}\n{traceback.format_exc()}', log_widget)
                    log('All selected binds processed', log_widget)
            except Exception as e:
                log(f"Error: {e} --\n{traceback.format_exc()}", log_widget)
                try:
                    mt_showerror('Error', str(e))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(frm, text='Generate & (optional) Apply', command=on_run).grid(column=0, row=row, sticky='w')
    ttk.Button(frm, text='Close', command=root.quit).grid(column=0, row=row, sticky='e')

    root.mainloop()


if __name__ == '__main__':
    build_gui()
