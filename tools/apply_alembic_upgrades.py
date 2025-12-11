#!/usr/bin/env python3
"""Apply Alembic migrations programmatically inside the Flask app context.

This script imports the application, pushes an app context and runs Alembic
`upgrade heads` using the migrations/alembic.ini config so `migrations/env.py`
has access to `current_app`.

CAUTION: Back up your instance DB files before running this script.
"""
import sys
from alembic.config import Config
from alembic import command

from app import create_app, db
from tools.autogen_migration_gui import (
    run_alembic_upgrade,
    run_alembic_stamp,
    run_alembic_revision,
    parse_upgrade_error_details,
    db_column_exists,
    db_table_exists,
    find_migration_creating_table,
    find_migration_adding_column,
    find_bulk_insert_values,
    find_migration_referencing_table,
)
from sqlalchemy import text
from sqlalchemy import create_engine as sa_create_engine
import argparse
from datetime import datetime
def log(msg, text_widget=None):
    msg = f"[{datetime.utcnow().isoformat()}] {msg}\n"
    if text_widget:
        try:
            text_widget.configure(state='normal')
            text_widget.insert(tk.END, msg)
            text_widget.see(tk.END)
            text_widget.configure(state='disabled')
        except Exception:
            print(msg)
    else:
        print(msg)
import os
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import shutil
from datetime import datetime


MT_ASK = messagebox.askyesno
MT_SHOWINFO = messagebox.showinfo
MT_SHOWERROR = messagebox.showerror


def main():
    parser = argparse.ArgumentParser(description='Apply Alembic migrations with automatic remediation')
    parser.add_argument('--no-backup', action='store_true', help='Do not back up instance DB files')
    parser.add_argument('--dry-run', action='store_true', help='Perform checks but do not modify DBs')
    parser.add_argument('--no-autogen', action='store_true', help='Do not autogenerate migrations')
    parser.add_argument('--generate-only', action='store_true', help='Only autogenerate migration(s), do not apply upgrades')
    args = parser.parse_args()
    # Add compatibility for module-level --no-gui invocation
    no_gui = '--no-gui' in sys.argv

    app = create_app()
    # Use autogen by default unless explicitly disabled
    autogen = not args.no_autogen
    generate_only = args.generate_only
    apply_upgrades_for_binds(app, list({'default': app.config.get('SQLALCHEMY_DATABASE_URI')}.keys()) + list((app.config.get('SQLALCHEMY_BINDS') or {}).keys()), no_backup=args.no_backup, dry_run=args.dry_run, log_widget=None, auto_stamp=True, auto_delete=True, auto_generate=autogen, generate_only=generate_only)


def apply_upgrades_for_binds(app, selected_binds, no_backup=False, dry_run=False, log_widget=None, auto_stamp=False, auto_delete=False, auto_generate=True, generate_only=False):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    # All DB operations need to be executed within an application context
    with app.app_context():
        binds = {'default': app.config.get('SQLALCHEMY_DATABASE_URI')}
        binds.update(app.config.get('SQLALCHEMY_BINDS') or {})
        # Back up DBs
        if not no_backup:
            ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            backup_dir = os.path.join(app.instance_path, 'backup', ts)
            os.makedirs(backup_dir, exist_ok=True)
            for f in os.listdir(app.instance_path):
                if f.endswith('.db'):
                    src = os.path.join(app.instance_path, f)
                    dst = os.path.join(backup_dir, f)
                    log(f'Backing up {src} -> {dst}', log_widget)
                    shutil.copy2(src, dst)
        # Upgrade per selected binds
        from app import db
        for name in selected_binds:
            target_bind = None if name == 'default' else name
            try:
                engine = db.get_engine(bind=target_bind)
            except Exception:
                log(f'get_engine failed for bind {name}; trying engines dict or engine property', log_widget)
                engine = None
                try:
                    engine = db.engines.get(target_bind) or db.engines.get(None)
                except Exception:
                    try:
                        engine = db.engine
                    except Exception:
                        engine = None
            # If we still don't have an engine, try creating one from the bind URI
            if engine is None:
                try:
                    uri = binds.get(name)
                    if uri:
                        log(f'Creating Engine for bind {name} from URI: {uri}', log_widget)
                        engine = sa_create_engine(uri)
                except Exception as e:
                    log(f'Failed to create Engine for bind {name}: {e}', log_widget)
            log(f'Upgrading bind: {name} -> {getattr(engine, "url", None) if engine is not None else "(engine unresolved)"}', log_widget)
            # Autogenerate revision files if requested
            if auto_generate:
                try:
                    # Determine metadata for this bind
                    metadata = None
                    try:
                        metadata = db.metadatas.get(name) if hasattr(db, 'metadatas') else None
                    except Exception:
                        metadata = None
                    if metadata is None:
                        metadata = getattr(db, 'metadata', None)
                    if metadata is not None:
                        log(f'Autogenerate: running autogenerate for bind {name}.', log_widget)
                        gen_file, info_msg = run_alembic_revision(app, engine, metadata, f'autogen: autogenerate for bind {name}', log_widget)
                        if gen_file:
                            log(f'Generated migration file: {gen_file}', log_widget)
                            if not dry_run and not generate_only:
                                ok2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget=log_widget)
                                log(f'Post-generate upgrade result: {ok2}, {err2}', log_widget)
                        else:
                            if info_msg:
                                log(f'Autogenerate info: {info_msg}', log_widget)
                            else:
                                log('Autogenerate: no migration generated (no schema changes).', log_widget)
                    else:
                        log('Autogenerate skipped: could not determine metadata for bind', log_widget)
                except Exception as e:
                    log(f'Autogenerate failed: {e}', log_widget)
        ok, err, category, rev_info = run_alembic_upgrade(engine, log_widget=log_widget)
        if not ok:
            log(f'Upgrade failed for bind {name}: {err} (category={category}, rev_info={rev_info})', log_widget)
            details = parse_upgrade_error_details(err)
            log(f'Parsed details: {details}', log_widget)
            failed_rev = details.get('rev') or (rev_info[0] if isinstance(rev_info, tuple) else rev_info)
            # Duplicate column: stamp if column exists
            if details.get('category') == 'duplicate_column' and details.get('table') and details.get('column'):
                table = details['table']
                column = details['column']
                try:
                    if db_column_exists(engine, table, column):
                        if dry_run:
                            log(f'(Dry) Would stamp revision {failed_rev} to skip duplicate column {table}.{column}', log_widget)
                        else:
                            rev_to_stamp = failed_rev
                            if not rev_to_stamp:
                                rev_to_stamp, _, _ = find_migration_adding_column(column, mig_path_hint=details.get('file') or failed_rev)
                            if rev_to_stamp:
                                do_stamp = auto_stamp or MT_ASK('Stamp migration?', f"Stamp revision {rev_to_stamp} to skip addition of duplicate column {table}.{column}?")
                                if do_stamp:
                                    log(f'Stamping revision {rev_to_stamp} to skip duplicate column {table}.{column}', log_widget)
                                    stamped, stamp_err = run_alembic_stamp(engine, rev_to_stamp, log_widget=log_widget)
                                log(f'Stamped: {stamped}, err: {stamp_err}', log_widget)
                                if stamped:
                                    ok2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget=log_widget)
                                    log(f'Retry result: {ok2}, {err2}', log_widget)
                    else:
                        log(f'Column {table}.{column} does not exist; cannot auto-stamp.', log_widget)
                except Exception as e:
                    log(f'Error checking/stamping duplicate column: {e}', log_widget)
            # Unique violation: attempt deduping
            elif details.get('category') == 'unique_violation' and details.get('table') and details.get('column'):
                table = details['table']
                column = details['column']
                mig_path = None
                if details.get('file'):
                    mig_path = os.path.join(repo_root, 'migrations', 'versions', details['file'])
                elif failed_rev:
                    import glob
                    ms = glob.glob(os.path.join(repo_root, 'migrations', 'versions', f"{failed_rev}_*.py"))
                    if ms:
                        mig_path = ms[0]
                vals = None
                if mig_path and os.path.exists(mig_path):
                    vals = find_bulk_insert_values(mig_path, table, column)
                if vals:
                    log(f'Detected duplicate insert values {vals} for {table}.{column}, attempting to delete and retry', log_widget)
                    if dry_run:
                        log('(Dry) Would delete duplicates for values: ' + str(vals), log_widget)
                    else:
                        try:
                            import re
                            def _safe_ident(name):
                                return re.match(r'^[A-Za-z0-9_]+$', name) is not None
                            if not (_safe_ident(table) and _safe_ident(column)):
                                raise ValueError('Unsafe table/column name')
                            do_delete = auto_delete or MT_ASK('Delete duplicates?', f"Delete duplicate rows in {table}.{column} for values {vals}? This will permanently remove rows from the DB.")
                            if do_delete:
                                with engine.begin() as conn:
                                    for v in vals:
                                        conn.execute(text(f"DELETE FROM {table} WHERE {column} = :val"), {'val': v})
                            ok2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget=log_widget)
                            log(f'Retry result after dedup: {ok2}, {err2}', log_widget)
                        except Exception as e:
                            log(f'Error deleting duplicates: {e}', log_widget)
                else:
                    # No values, fallback to stamping
                    if failed_rev:
                        if dry_run:
                            log(f'(Dry) Would stamp revision {failed_rev} to skip unique violation', log_widget)
                        else:
                            stamped, stamp_err = run_alembic_stamp(engine, failed_rev, log_widget=log_widget)
                            log(f'Stamped: {stamped}, err: {stamp_err}', log_widget)
                            if stamped:
                                ok2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget=log_widget)
                                log(f'Retry result after stamp: {ok2}, {err2}', log_widget)
            # Missing table: attempt to find/create migration or stamp
            elif details.get('category') == 'missing_table' and details.get('table'):
                table = details['table']
                rev_create, mig_path = find_migration_creating_table(table)
                rev_to_stamp = rev_create
                if not rev_to_stamp:
                    candidates = find_migration_referencing_table(table)
                    if candidates:
                        rev_to_stamp, mig_path = candidates[0]
                if rev_to_stamp:
                    if dry_run:
                        log(f'(Dry) Would stamp revision {rev_to_stamp} to resolve missing table {table}', log_widget)
                    else:
                        stamped, stamp_err = run_alembic_stamp(engine, rev_to_stamp, log_widget=log_widget)
                        log(f'Stamped creation rev: {stamped}, err: {stamp_err}', log_widget)
                        if stamped:
                            ok2, err2, cat2, rev_info2 = run_alembic_upgrade(engine, log_widget=log_widget)
                            log(f'Retry result after stamp creation: {ok2}, {err2}', log_widget)
                else:
                    log(f'No migration creating/referencing table {table} found; manual resolution needed', log_widget)
            else:
                log('Unhandled or unknown upgrade error; manual intervention required', log_widget)
        else:
            log(f'Upgrade succeeded for bind {name}', log_widget)
            # Post-upgrade verification for users bind: check only_password_reset_emails
            if name == 'users':
                try:
                    if db_table_exists(engine, 'user'):
                        if db_column_exists(engine, 'user', 'only_password_reset_emails'):
                            log('Verified: user.only_password_reset_emails exists', log_widget)
                        else:
                            log('Warning: user.only_password_reset_emails is missing after upgrade', log_widget)
                        # Also verify preferred_theme exists for user
                        if db_column_exists(engine, 'user', 'preferred_theme'):
                            log('Verified: user.preferred_theme exists', log_widget)
                        else:
                            log('Warning: user.preferred_theme is missing after upgrade', log_widget)
                except Exception as e:
                    log(f'Error during post-upgrade verification: {e}', log_widget)


def build_gui():
    # Build a small Tk GUI for selecting binds and running upgrades
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from app import create_app, db
    app = create_app()
    root = tk.Tk()
    root.title('Auto-Update DB GUI')
    frm = ttk.Frame(root, padding=8)
    frm.grid()

    # Binds
    binds = {'default': app.config.get('SQLALCHEMY_DATABASE_URI')}
    binds.update(app.config.get('SQLALCHEMY_BINDS') or {})
    ttk.Label(frm, text='Select binds to upgrade:').grid(column=0, row=0, sticky='w')
    bind_vars = {}
    r = 1
    for name, uri in binds.items():
        v = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text=f'{name} ({uri})', variable=v).grid(column=0, row=r, sticky='w')
        bind_vars[name] = v
        r += 1
    # Add select/deselect all controls
    def select_all():
        for v in bind_vars.values():
            v.set(True)
    def deselect_all():
        for v in bind_vars.values():
            v.set(False)
    ttk.Button(frm, text='Select All', command=select_all).grid(column=1, row=1, sticky='w')
    ttk.Button(frm, text='Deselect All', command=deselect_all).grid(column=1, row=2, sticky='w')

    # Options
    backup_var = tk.BooleanVar(value=True)
    dry_var = tk.BooleanVar(value=False)
    auto_stamp_var = tk.BooleanVar(value=True)
    auto_delete_var = tk.BooleanVar(value=True)
    run_on_start_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(frm, text='Backup DBs before upgrade', variable=backup_var).grid(column=0, row=r, sticky='w')
    r += 1
    ttk.Checkbutton(frm, text='Dry run (do not modify DBs)', variable=dry_var).grid(column=0, row=r, sticky='w')
    r += 1
    ttk.Checkbutton(frm, text='Auto-stamp migrations for duplicate columns', variable=auto_stamp_var).grid(column=0, row=r, sticky='w')
    r += 1
    ttk.Checkbutton(frm, text='Auto-delete duplicates for unique violations', variable=auto_delete_var).grid(column=0, row=r, sticky='w')
    r += 1
    ttk.Checkbutton(frm, text='Run on startup (automatic run)', variable=run_on_start_var).grid(column=0, row=r, sticky='w')
    r += 1

    # Provide main-thread wrappers for messagebox calls to be used by worker
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

    global MT_ASK, MT_SHOWINFO, MT_SHOWERROR
    MT_ASK = lambda t, m: _call_in_main_thread(messagebox.askyesno, t, m)
    MT_SHOWINFO = lambda t, m: _call_in_main_thread(messagebox.showinfo, t, m)
    MT_SHOWERROR = lambda t, m: _call_in_main_thread(messagebox.showerror, t, m)

    # Action buttons
    def log(msg, text_widget=None):
        from datetime import datetime
        msg = f"[{datetime.utcnow().isoformat()}] {msg}\n"
        if text_widget:
            text_widget.configure(state='normal')
            text_widget.insert(tk.END, msg)
            text_widget.see(tk.END)
            text_widget.configure(state='disabled')
        else:
            print(msg)

    def on_run():
        selected = [name for name, v in bind_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning('No binds selected', 'Select at least one bind to upgrade')
            return
        # Disable buttons while running
        run_btn.configure(state='disabled')
        def worker():
            import traceback
            try:
                apply_upgrades_for_binds(app, selected, no_backup=not backup_var.get(), dry_run=dry_var.get(), log_widget=log_text, auto_stamp=auto_stamp_var.get(), auto_delete=auto_delete_var.get())
            except Exception:
                log(traceback.format_exc(), log_text)
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        # Poll for thread completion and re-enable button when done
        def poll():
            if t.is_alive():
                root.after(500, poll)
            else:
                run_btn.configure(state='normal')
        root.after(500, poll)
    # Auto run on startup
    if run_on_start_var.get():
        # call invoke after GUI widgets are created and loop started
        root.after(100, lambda: run_btn.invoke())

    run_btn = ttk.Button(frm, text='Run Upgrade', command=on_run)
    run_btn.grid(column=0, row=r, sticky='w')
    r += 1

    # Log
    ttk.Label(frm, text='Output:').grid(column=0, row=r, sticky='w')
    r += 1
    log_text = scrolledtext.ScrolledText(frm, width=100, height=20, state='disabled')
    log_text.grid(column=0, row=r, sticky='nsew')

    root.mainloop()


if __name__ == '__main__':
    # Default to GUI when run directly; support --no-gui to run noninteractive
    if '--no-gui' in sys.argv:
        # Remove the --no-gui flag so argparse doesn't complain
        sys.argv = [a for a in sys.argv if a != '--no-gui']
        main()
    else:
        build_gui()
