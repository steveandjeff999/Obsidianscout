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
  - copy files from the new release into the current repo root.
  - For configured user-data paths (preserved paths), it will merge in any NEW files or directories
    from the release without overwriting or deleting existing content in those paths.
  - preserve file metadata where possible

Default preserve paths (top-level names): instance, uploads, config, migrations, translations, ssl, .env, app_config.json, .venv, venv

Be sure the server is stopped before running this script. Run with --dry-run to preview changes.
"""

from __future__ import annotations

import argparse
import logging
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


def merge_add_only(src_path: Path, dst_path: Path, dry_run: bool, log: callable, repo_root: Path) -> list[str]:
    """
    Recursively copies items from src_path to dst_path ONLY if they don't already exist in dst_path.
    This allows adding new files to preserved directories without overwriting existing ones.
    Returns a list of relative paths of items that were added.
    """
    added_items = []

    # If the source is a directory, iterate through its contents
    if src_path.is_dir():
        # If the destination directory doesn't exist at all, copy the entire source tree
        if not dst_path.exists():
            log(f"[Preserved Add] Adding new directory: '{dst_path.relative_to(repo_root)}'")
            if not dry_run:
                shutil.copytree(src_path, dst_path)
            # Add all contained paths to the list
            for root, _, files in os.walk(src_path):
                for name in files:
                    added_items.append(str(Path(root) / name))
            return added_items

        # If destination exists and is a directory, recurse
        if dst_path.is_dir():
            for src_item in src_path.iterdir():
                dst_item = dst_path / src_item.name
                added_items.extend(merge_add_only(src_item, dst_item, dry_run, log, repo_root))
        # If dst_path exists but is a file, we don't touch it
        return added_items

    # If the source is a file
    elif src_path.is_file():
        if not dst_path.exists():
            log(f"[Preserved Add] Adding new file: '{dst_path.relative_to(repo_root)}'")
            if not dry_run:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst_path)
            return [str(dst_path)]
        else:
            # File exists at destination, do nothing
            return []
    
    return added_items


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
            target = repo_root / name

            # Skip VCS directories inside release (optional)
            if name in ('.git', '.github'):
                skipped.append((name, 'VCS - skipped'))
                continue

            # CRITICAL: Protect ALL database files from being overwritten
            # This prevents database corruption during updates
            if (name.endswith('.db') or name.endswith('.db-wal') or name.endswith('.db-shm') or 
                name.endswith('.sqlite') or name.endswith('.sqlite3')):
                _log(f" Database file protection: Skipping '{name}' to prevent corruption")
                skipped.append((name, 'DATABASE PROTECTED - skipped to prevent corruption'))
                continue

            # For preserved paths, merge new files/dirs without overwriting existing content.
            if name in preserve:
                try:
                    # Special-case app_config.json: merge JSON keys so we don't overwrite
                    # operator-managed secrets (preserve existing keys, add new keys from release)
                    if name == 'app_config.json' and entry.is_file():
                        try:
                            src_text = entry.read_text(encoding='utf-8')
                            src_json = json.loads(src_text)
                        except Exception:
                            src_json = {}

                        if target.exists() and target.is_file():
                            try:
                                dst_text = target.read_text(encoding='utf-8')
                                dst_json = json.loads(dst_text)
                            except Exception:
                                dst_json = {}

                            # Backup existing target before modifying
                            try:
                                backup_target = backup_root / target.name
                                if not dry_run:
                                    backup_root.mkdir(parents=True, exist_ok=True)
                                    if backup_target.exists():
                                        backup_target = Path(str(backup_target) + f"_{int(time.time())}")
                                    shutil.copy2(target, backup_target)
                            except Exception:
                                pass

                            # Merge: keep dst values, only add keys from src that are missing
                            added_keys = []
                            for k, v in (src_json or {}).items():
                                if k not in dst_json:
                                    dst_json[k] = v
                                    added_keys.append(k)

                            if added_keys:
                                if not dry_run:
                                    try:
                                        target.write_text(json.dumps(dst_json, indent=2), encoding='utf-8')
                                    except Exception as e:
                                        _log(f"ERROR writing merged app_config.json: {e}")
                                skipped.append((name, f'preserved (merged {len(added_keys)} new key(s))'))
                            else:
                                skipped.append((name, 'preserved (no new keys)'))
                        else:
                            # Destination missing - copy the file over as-is (it's preserved path)
                            if not dry_run:
                                try:
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(entry, target)
                                except Exception as e:
                                    _log(f"ERROR copying new preserved file '{name}': {e}")
                            skipped.append((name, 'preserved (new file added)'))
                        continue

                    # Default preserved-path behavior: add-only merge
                    added_items = merge_add_only(entry, target, dry_run=dry_run, log=_log, repo_root=repo_root)
                    if added_items:
                        summary = f'preserved (merged {len(added_items)} new item{"s" if len(added_items) > 1 else ""})'
                        skipped.append((name, summary))
                    else:
                        skipped.append((name, 'preserved (no new files)'))
                except Exception as e:
                    _log(f"ERROR merging preserved path '{entry.name}': {e}")
                continue

            # For all other paths, perform a full backup and replace.
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

