#!/usr/bin/env python3
"""
Update the current installation from a downloaded release directory or ZIP.

Usage:
  python update_from_release.py /path/to/new_release_dir
  python update_from_release.py /path/to/new_release.zip --zip

The script will:
  - refuse to run if common server ports appear in use (5000,8000,8080,80) unless --force is provided
  - extract a ZIP release to a temp dir if --zip is specified
  - create a timestamped backup of files/directories that will be overwritten under ./backups/
  - copy files from the new release into the current repo root, skipping (preserving) configured user-data paths
  - preserve file metadata where possible

Default preserve paths (top-level names): instance, uploads, config, migrations, translations, ssl, .env, app_config.json, .venv, venv

Be sure the server is stopped before running this script. Run with --dry-run to preview changes.
"""

from __future__ import annotations

import argparse
from asyncio import log
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
import socket
import threading
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
except Exception:
    tk = None


DEFAULT_PRESERVE = {
    'instance',
    'uploads',
    'config',
    'migrations',
    'translations',
    'ssl',
    '.env',
    'app_config.json',
    '.venv',
    'venv',
    'env'
}

COMMON_PORTS_TO_CHECK = [5000, 8000, 8080, 80]


def port_in_use(port: int, host: str = '127.0.0.1') -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except Exception:
        return False


def check_server_running() -> list[int]:
    in_use = []
    for p in COMMON_PORTS_TO_CHECK:
        if port_in_use(p):
            in_use.append(p)
    return in_use


def copy_item(src: Path, dst: Path, backup_root: Path, dry_run: bool = False, log=None):
    """Copy a file or directory from src to dst. If dst exists, move it into backup_root preserving path.

    log: optional callable that accepts a string for logging.
    """
    def _log(m):
        if log:
            try:
                log(m)
            except Exception:
                print(m)
        else:
            print(m)

    if dst.exists():
        backup_target = backup_root / dst.name
        _log(f"Backing up existing '{dst}' -> '{backup_target}'")
        if not dry_run:
            # If backup target exists, add timestamp suffix
            if backup_target.exists():
                backup_target = Path(str(backup_target) + f"_{int(time.time())}")
            if dst.is_dir():
                shutil.copytree(dst, backup_target)
            else:
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup_target)

    _log(f"Replacing '{dst}' with '{src}'")
    if not dry_run:
        # Remove existing target
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()

        # Copy from src
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def perform_update(release: str | Path, is_zip: bool = False, preserve_extra: set[str] | None = None,
                   dry_run: bool = False, force: bool = False, repo_root: Path | None = None,
                   log_callback=None):
    """Perform the update. log_callback, if provided, should be a callable that accepts a string."""
    def _log(m: str):
        if log_callback:
            try:
                log_callback(m)
            except Exception:
                print(m)
        else:
            print(m)

    repo_root = Path(__file__).resolve().parent if repo_root is None else Path(repo_root).resolve()
    release_path = Path(release).expanduser().resolve()

    # Build preserve set
    preserve = set(DEFAULT_PRESERVE)
    if preserve_extra:
        for p in preserve_extra:
            p = p.strip()
            if p:
                preserve.add(p)

    # Check server running
    running_ports = check_server_running()
    if running_ports and not force:
        _log("ERROR: It looks like the server may be running (ports in use):")
        _log(', '.join(str(p) for p in running_ports))
        _log("Stop the server and re-run, or use --force to override (not recommended).")
        return 1
    elif running_ports:
        _log(f"Warning: server ports in use, continuing because --force was supplied: {running_ports}")

    # Handle zip extraction
    tempdir = None
    try:
        if is_zip:
            if not release_path.is_file():
                _log(f"ZIP file not found: {release_path}")
                return 1
            tempdir = Path(tempfile.mkdtemp(prefix='obs_update_'))
            _log(f"Extracting ZIP to temporary dir: {tempdir}")
            with zipfile.ZipFile(release_path, 'r') as zf:
                zf.extractall(tempdir)

            # If the zip contains a single top-level folder, use that as the release dir
            entries = [p for p in tempdir.iterdir() if p.name != '__MACOSX']
            if len(entries) == 1 and entries[0].is_dir():
                release_dir = entries[0]
            else:
                release_dir = tempdir
        else:
            if not release_path.exists():
                _log(f"Release path not found: {release_path}")
                return 1
            release_dir = release_path

        _log(f"Using release directory: {release_dir}")

        # Create backup dir
        backup_root = repo_root / 'backups' / f"update_backup_{datetime.now():%Y%m%d_%H%M%S}"
        _log(f"Backup root: {backup_root}")
        if not dry_run:
            backup_root.mkdir(parents=True, exist_ok=True)

        # Iterate top-level entries in release_dir
        changed = []
        skipped = []
        for entry in release_dir.iterdir():
            name = entry.name
            # Skip VCS directories inside release (optional)
            if name in ('.git', '.github'):
                skipped.append((name, 'VCS - skipped'))
                continue

            # Preserve top-level names
            if name in preserve:
                skipped.append((name, 'preserved'))
                continue

            target = repo_root / name
            try:
                copy_item(entry, target, backup_root, dry_run=dry_run, log=_log)
                changed.append(name)
            except Exception as e:
                _log(f"ERROR copying {entry} -> {target}: {e}")
                # Continue to next

        _log('\nUpdate summary:')
        _log(f"  Changed/Replaced: {len(changed)} items")
        if changed:
            for c in changed:
                _log(f"    - {c}")
        _log(f"  Skipped/Preserved: {len(skipped)} items")
        if skipped:
            for s, reason in skipped:
                _log(f"    - {s} ({reason})")

        if dry_run:
            _log('\nDry-run mode: no files were changed. Remove --dry-run to perform the update.')
        else:
            _log('\nUpdate applied. A backup of replaced files is in:')
            _log(f"  {backup_root}")
            _log('\nNext steps:')
            _log('  - Review the backup folder before deleting it.')
            _log('  - If the update included dependency changes, run: pip install -r requirements.txt')
            _log('  - Run database migrations if needed (check project docs).')

    finally:
        # Cleanup tempdir if used
        if tempdir and tempdir.exists():
            try:
                shutil.rmtree(tempdir)
            except Exception:
                pass

    return 0


def launch_gui():
    if tk is None:
        print("Tkinter is not available in this Python environment. Install tk and try again or run CLI mode.")
        return

    root = tk.Tk()
    root.title('Obsidian-Scout Updater')

    frm = tk.Frame(root, padx=8, pady=8)
    frm.pack(fill='both', expand=True)

    tk.Label(frm, text='Release path (dir or zip):').grid(row=0, column=0, sticky='w')
    release_var = tk.StringVar()
    e_release = tk.Entry(frm, textvariable=release_var, width=60)
    e_release.grid(row=0, column=1, padx=4)

    def browse_file():
        p = filedialog.askopenfilename(title='Select release ZIP or file')
        if p:
            release_var.set(p)

    def browse_dir():
        p = filedialog.askdirectory(title='Select release directory')
        if p:
            release_var.set(p)

    tk.Button(frm, text='Browse File', command=browse_file).grid(row=0, column=2)
    tk.Button(frm, text='Browse Dir', command=browse_dir).grid(row=0, column=3)

    is_zip_var = tk.BooleanVar(value=False)
    tk.Checkbutton(frm, text='ZIP archive', variable=is_zip_var).grid(row=1, column=0, sticky='w')

    tk.Label(frm, text='Extra preserve (comma-separated top-level names):').grid(row=2, column=0, columnspan=2, sticky='w')
    preserve_var = tk.StringVar()
    tk.Entry(frm, textvariable=preserve_var, width=60).grid(row=2, column=1, padx=4, columnspan=3)

    dry_run_var = tk.BooleanVar(value=True)
    tk.Checkbutton(frm, text='Dry run (preview)', variable=dry_run_var).grid(row=3, column=0, sticky='w')
    force_var = tk.BooleanVar(value=False)
    tk.Checkbutton(frm, text='Force (override running checks)', variable=force_var).grid(row=3, column=1, sticky='w')

    log_box = scrolledtext.ScrolledText(frm, width=100, height=20)
    log_box.grid(row=4, column=0, columnspan=4, pady=8)

    # Thread-safe log queue
    log_q = []
    log_lock = threading.Lock()

    def gui_log(msg: str):
        with log_lock:
            log_q.append(str(msg))

    def flush_logs():
        with log_lock:
            while log_q:
                s = log_q.pop(0)
                log_box.insert('end', s + '\n')
                log_box.see('end')
        root.after(200, flush_logs)

    def run_update_thread():
        release = release_var.get().strip()
        if not release:
            messagebox.showwarning('Missing path', 'Please choose a release directory or ZIP file')
            return

        extra = set([p.strip() for p in preserve_var.get().split(',') if p.strip()])

        def worker():
            try:
                gui_log('Starting update...')
                rc = perform_update(release, is_zip=is_zip_var.get(), preserve_extra=extra,
                                    dry_run=dry_run_var.get(), force=force_var.get(), log_callback=gui_log)
                gui_log(f'Update finished with exit code: {rc}')
            except Exception as e:
                gui_log(f'Unhandled error: {e}')

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    btn_frame = tk.Frame(frm)
    btn_frame.grid(row=5, column=0, columnspan=4, pady=4)
    tk.Button(btn_frame, text='Run Update', command=run_update_thread, bg='#4CAF50', fg='white').pack(side='left', padx=4)
    tk.Button(btn_frame, text='Clear Log', command=lambda: log_box.delete('1.0', 'end')).pack(side='left', padx=4)
    tk.Button(btn_frame, text='Close', command=root.destroy).pack(side='left', padx=4)

    root.after(200, flush_logs)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Update installation from downloaded release while preserving user data.")
    parser.add_argument('release', help='Path to the new release directory or ZIP file')
    parser.add_argument('--zip', action='store_true', help='Treat the release path as a ZIP archive to extract')
    parser.add_argument('--preserve', help='Comma-separated extra top-level names to preserve', default='')
    parser.add_argument('--dry-run', action='store_true', help='Show actions without making changes')
    parser.add_argument('--force', action='store_true', help='Force update even if server ports seem in use')
    args = parser.parse_args()

    preserve = set(DEFAULT_PRESERVE)
    if args.preserve:
        for p in args.preserve.split(','):
            p = p.strip()
            if p:
                preserve.add(p)

    rc = perform_update(args.release, is_zip=args.zip, preserve_extra=preserve,
                        dry_run=args.dry_run, force=args.force)
    sys.exit(rc)


if __name__ == '__main__':
    # Launch GUI when no CLI args provided
    if len(sys.argv) == 1:
        launch_gui()
    else:
        main()
