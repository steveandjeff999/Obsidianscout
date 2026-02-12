"""
prepare_for_publish.py

This utility only scans and modifies JSON files in the repository.
It extracts likely secret values from JSON files, writes a backup JSON to the user's
Downloads folder, replaces the secret values with placeholders, and can restore from backups.

Includes a simple Tkinter UI to review the JSON files and summary before applying changes.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent

# Pattern for keys in JSON that look like secrets
GENERIC_SECRET_KEYS = re.compile(r".*(api[_-]?key|secret|password|token|vapid).*", re.IGNORECASE)


def downloads_folder() -> Path:
    home = Path.home()
    d = home / "Downloads"
    return d if d.exists() else home


def find_json_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*.json"):
        if p.is_file():
            # Skip known runtime-generated or intentionally excluded files
            try:
                rel = p.relative_to(root)
                if rel.as_posix().lower() == "instance/vapid_keys.json":
                    continue
            except Exception:
                pass
            if any(part.startswith(".") for part in p.parts):
                continue
            if "__pycache__" in p.parts:
                continue
            if ".git" in p.parts:
                continue
            files.append(p)
    return files


def extract_from_json_file(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    found: Dict[str, str] = {}

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                keyname = f"{prefix}{k}"
                if isinstance(v, (str, int, float)):
                    if GENERIC_SECRET_KEYS.match(k) or k in ("password", "private_key", "privateKey"):
                        found[keyname] = str(v)
                else:
                    walk(v, prefix=f"{keyname}.")

    walk(data)
    return found


def scan_json_files(root: Path) -> Dict[str, Dict[str, str]]:
    files = find_json_files(root)
    results: Dict[str, Dict[str, str]] = {}
    for f in files:
        rel = f.relative_to(root)
        found = extract_from_json_file(f)
        if found:
            results[str(rel)] = found
    return results


def scrub_json_from_scan(root: Path, scan_results: Dict[str, Dict[str, str]], backup_file: Optional[Path] = None) -> Tuple[Path, Dict[str, Dict[str, str]]]:
    backup: Dict[str, Dict[str, str]] = {}
    # Special-case: always redact app_config.json JWT secret and set generate flag
    try:
        app_cfg_rel = 'app_config.json'
        app_cfg_path = root / app_cfg_rel
        if app_cfg_path.exists():
            try:
                content = json.loads(app_cfg_path.read_text(encoding='utf-8'))
            except Exception:
                content = {}

            # Backup existing JWT_SECRET_KEY and JWT_GENERATE_NEW values (if any)
            orig_jwt = content.get('JWT_SECRET_KEY') if isinstance(content, dict) else None
            orig_gen = content.get('JWT_GENERATE_NEW') if isinstance(content, dict) else None
            if orig_jwt is not None or orig_gen is not None:
                backup.setdefault(app_cfg_rel, {})['JWT_SECRET_KEY'] = orig_jwt
                backup.setdefault(app_cfg_rel, {})['JWT_GENERATE_NEW'] = orig_gen

            # Also backup VAPID keys if present (so GUI scrub also redacts them)
            orig_vapid_priv = content.get('VAPID_PRIVATE_KEY') if isinstance(content, dict) else None
            orig_vapid_pub = content.get('VAPID_PUBLIC_KEY') if isinstance(content, dict) else None
            orig_vapid_gen = content.get('VAPID_GENERATE_NEW') if isinstance(content, dict) else None
            if orig_vapid_priv is not None or orig_vapid_pub is not None or orig_vapid_gen is not None:
                backup.setdefault(app_cfg_rel, {})['VAPID_PRIVATE_KEY'] = orig_vapid_priv
                backup.setdefault(app_cfg_rel, {})['VAPID_PUBLIC_KEY'] = orig_vapid_pub
                backup.setdefault(app_cfg_rel, {})['VAPID_GENERATE_NEW'] = orig_vapid_gen

            # Replace JWT and VAPID values with placeholders and enable generation on startup
            try:
                if not isinstance(content, dict):
                    content = {}
                changed = False
                if content.get('JWT_SECRET_KEY'):
                    content['JWT_SECRET_KEY'] = '[REDACTED_JWT_SECRET_KEY]'
                    content['JWT_GENERATE_NEW'] = True
                    changed = True
                # redact VAPID keys if present
                if content.get('VAPID_PRIVATE_KEY'):
                    content['VAPID_PRIVATE_KEY'] = '[REDACTED_VAPID_PRIVATE_KEY]'
                    changed = True
                if content.get('VAPID_PUBLIC_KEY'):
                    content['VAPID_PUBLIC_KEY'] = '[REDACTED_VAPID_PUBLIC_KEY]'
                    changed = True
                if not content.get('VAPID_GENERATE_NEW'):
                    # set flag to force regeneration on startup
                    content['VAPID_GENERATE_NEW'] = True
                    changed = True
                if changed:
                    app_cfg_path.write_text(json.dumps(content, indent=2), encoding='utf-8')
            except Exception:
                pass

            # If app_config.json was included in scan_results, remove it to avoid double-processing
            try:
                if app_cfg_rel in scan_results:
                    del scan_results[app_cfg_rel]
            except Exception:
                pass
    except Exception:
        pass
    for rel_str, secrets in scan_results.items():
        target = root / rel_str
        if not target.exists():
            continue
        try:
            content = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            continue

        def walk_and_replace(obj, prefix=""):
            if isinstance(obj, dict):
                for k in list(obj.keys()):
                    keyname = f"{prefix}{k}"
                    if keyname in secrets:
                        backup.setdefault(rel_str, {})[keyname] = secrets[keyname]
                        obj[k] = f"[REDACTED_{k}]"
                    else:
                        obj[k] = walk_and_replace(obj[k], prefix=f"{keyname}.")
                return obj
            elif isinstance(obj, list):
                return [walk_and_replace(x, prefix=prefix) for x in obj]
            else:
                return obj

        new_content = walk_and_replace(content)
        target.write_text(json.dumps(new_content, indent=2), encoding="utf-8")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if backup_file is None:
        downloads = downloads_folder()
        backup_file = downloads / f"obsidian_secrets_backup_{ts}.json"

    # Also modify `run.py` to set USE_POSTGRES and USE_WAITRESS to False for publishing.
    try:
        run_rel = 'run.py'
        run_path = root / run_rel
        if run_path.exists():
            try:
                orig_run = run_path.read_text(encoding='utf-8')
                # Store original content so it can be restored later
                backup.setdefault(run_rel, {})['original_content'] = orig_run
                new_run = orig_run
                # Replace assignments robustly allowing whitespace/comments
                new_run = re.sub(r'(?m)^(\s*USE_POSTGRES\s*=\s*).+$', r'\1False', new_run)
                new_run = re.sub(r'(?m)^(\s*USE_WAITRESS\s*=\s*).+$', r'\1False', new_run)
                if new_run != orig_run:
                    run_path.write_text(new_run, encoding='utf-8')
                    print("Modified run.py: set USE_POSTGRES and USE_WAITRESS to False for publishing")
            except Exception:
                pass
    except Exception:
        pass

    backup_file.write_text(json.dumps(backup, indent=2), encoding="utf-8")
    return backup_file, backup


def restore_from_backup(root: Path, backup_path: Path) -> None:
    try:
        data = json.loads(backup_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Could not read backup file: {e}")
        return

    for rel_str, secrets in data.items():
        target = root / rel_str
        if not target.exists():
            print(f"Skipping {rel_str}: file not found")
            continue
        # Special-case: restore original `run.py` content if present in backup
        if rel_str == 'run.py':
            if isinstance(secrets, dict) and 'original_content' in secrets:
                try:
                    target.write_text(secrets['original_content'], encoding='utf-8')
                    print(f"Restored secrets in {rel_str}")
                except Exception as e:
                    print(f"Could not restore {rel_str}: {e}")
            else:
                print(f"Skipping run.py: no original content in backup")
            continue
        try:
            content = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            print(f"Skipping JSON {rel_str}: parse error")
            continue

        def walk_and_restore(obj, prefix=""):
            if isinstance(obj, dict):
                for k in list(obj.keys()):
                    keyname = f"{prefix}{k}"
                    if keyname in secrets:
                        obj[k] = secrets[keyname]
                    else:
                        obj[k] = walk_and_restore(obj[k], prefix=f"{keyname}.")
                return obj
            elif isinstance(obj, list):
                return [walk_and_restore(x, prefix=prefix) for x in obj]
            else:
                return obj

        new_content = walk_and_restore(content)
        target.write_text(json.dumps(new_content, indent=2), encoding="utf-8")
        print(f"Restored secrets in {rel_str}")


def launch_gui():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext
    except Exception as e:
        print("Tkinter not available:", e)
        return

    class App:
        def __init__(self, master):
            self.master = master
            master.title("Prepare for Publish - JSON-only")
            master.geometry("900x700")

            btn_frame = tk.Frame(master)
            btn_frame.pack(fill=tk.X, padx=8, pady=6)

            self.scan_btn = tk.Button(btn_frame, text="Scan JSON Files", command=self.scan)
            self.scan_btn.pack(side=tk.LEFT, padx=4)

            self.apply_btn = tk.Button(btn_frame, text="Apply Scrub", command=self.apply, state=tk.DISABLED)
            self.apply_btn.pack(side=tk.LEFT, padx=4)

            self.restore_btn = tk.Button(btn_frame, text="Restore From Backup", command=self.restore)
            self.restore_btn.pack(side=tk.LEFT, padx=4)

            self.quit_btn = tk.Button(btn_frame, text="Quit", command=master.quit)
            self.quit_btn.pack(side=tk.RIGHT, padx=4)

            self.summary = scrolledtext.ScrolledText(master, wrap=tk.WORD)
            self.summary.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

            self.scan_results: Dict[str, Dict[str, str]] = {}
            self.last_backup: Optional[Path] = None

        def scan(self):
            self.summary.delete(1.0, tk.END)
            self.summary.insert(tk.END, "Scanning JSON files for secrets...\n")
            self.master.update()
            results = scan_json_files(ROOT)
            self.scan_results = results
            if not results:
                self.summary.insert(tk.END, "No likely secrets found in JSON files.\n")
                self.apply_btn.config(state=tk.DISABLED)
                return

            self.summary.insert(tk.END, f"Found secrets in {len(results)} JSON file(s):\n\n")
            total_keys = 0
            for rel, kv in sorted(results.items()):
                self.summary.insert(tk.END, f"{rel}:\n")
                for k, v in kv.items():
                    total_keys += 1
                    display = v if len(v) <= 60 else v[:57] + "..."
                    self.summary.insert(tk.END, f"  - {k}: {display}\n")
                self.summary.insert(tk.END, "\n")

            self.summary.insert(tk.END, f"\nTotal potential secret values found in JSON: {total_keys}\n")
            self.summary.insert(tk.END, "\nClick 'Apply Scrub' to remove these secrets from JSON files and create a backup in your Downloads folder.\n")
            self.apply_btn.config(state=tk.NORMAL)

        def apply(self):
            if not self.scan_results:
                messagebox.showinfo("Nothing to do", "No scan results to apply.")
                return
            if not messagebox.askyesno("Confirm", "This will replace detected secret values in JSON files with placeholders and save a backup to your Downloads folder. Continue?"):
                return
            self.summary.insert(tk.END, "\nApplying JSON scrub...\n")
            self.master.update()
            backup_path, backup = scrub_json_from_scan(ROOT, self.scan_results, None)
            self.last_backup = backup_path
            self.summary.insert(tk.END, f"Done. Backup written to: {backup_path}\n\n")
            self.summary.insert(tk.END, "Summary of changes:\n")
            for rel, kv in sorted(backup.items()):
                self.summary.insert(tk.END, f"{rel}: {len(kv)} key(s) redacted\n")
            self.apply_btn.config(state=tk.DISABLED)

        def restore(self):
            path = filedialog.askopenfilename(title="Select backup JSON", filetypes=[("JSON files","*.json"), ("All files","*.*")])
            if not path:
                return
            try:
                restore_from_backup(ROOT, Path(path))
                messagebox.showinfo("Restore complete", f"Restored secrets from {path}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not restore: {e}")

    root = tk.Tk()
    app = App(root)
    root.mainloop()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare repository for publishing by removing secrets from JSON files only")
    parser.add_argument("--backup", help="Path to write backup file (optional)")
    parser.add_argument("--restore", help="Path to backup file to restore")
    parser.add_argument("--gui", action="store_true", help="Launch a Tkinter GUI to review and apply changes")
    args = parser.parse_args(argv)

    if args.restore:
        backup_path = Path(args.restore)
        if not backup_path.exists():
            print("Backup file not found")
            return 2
        restore_from_backup(ROOT, backup_path)
        return 0

    if args.gui or (len(sys.argv) == 1):
        try:
            launch_gui()
            return 0
        except Exception as e:
            print("GUI failed to launch, falling back to CLI mode:", e)

    if args.backup:
        custom = Path(args.backup)
        scan_results = scan_json_files(ROOT)
        backup_path, backup = scrub_json_from_scan(ROOT, scan_results, None)
        shutil.copy(backup_path, custom)
        print(f"Copied backup to {custom}")
        return 0

    scan_results = scan_json_files(ROOT)
    if not scan_results:
        print("No likely secrets found in JSON files.")
        return 0
    backup_path, backup = scrub_json_from_scan(ROOT, scan_results, None)
    print(f"Scrub complete. Backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
prepare_for_publish.py

Utility to remove secrets (API keys, email passwords, VAPID keys, etc.) from the repo
and save them to a timestamped backup JSON in the user's Downloads folder so they can be
restored after publishing.

This version includes a simple Tkinter UI to scan, review detected secrets, apply scrubbing,
and show a summary of changes.

Usage (CLI):
  python prepare_for_publish.py --restore /path/to/backup.json # restore secrets
  python prepare_for_publish.py --backup /path/to/backup.json  # write backup to custom path after scrub

Usage (GUI):
  python prepare_for_publish.py --gui
  python prepare_for_publish.py            # launches GUI by default if available

Notes:
- Script is conservative: it looks for common key names and simple inline assignments.
- Always verify backups before publishing.
"""


import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent

# Generic key patterns in JSON or env files to scrub if they look like secrets
GENERIC_SECRET_KEYS = re.compile(r".*(api[_-]?key|secret|password|token|vapid).*", re.IGNORECASE)

# Regex for inline assignments in Python or .env style files
ASSIGNMENT_RE = re.compile(r"^(?P<key>[A-Za-z0-9_\-\.]+)\s*[:=]\s*['\"](?P<val>.+?)['\"]\s*$")


def downloads_folder() -> Path:
    home = Path.home()
    d = home / "Downloads"
    if d.exists():
        return d
    return home


def find_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            if any(part.startswith(".") for part in p.parts):
                continue
            if "__pycache__" in p.parts:
                continue
            if ".git" in p.parts:
                continue
            if p.suffix.lower() in {".py", ".json", ".env", ".txt", ".cfg", ".ini"}:
                files.append(p)
    return files


def extract_from_json_file(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    found: Dict[str, str] = {}

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                keyname = f"{prefix}{k}"
                if isinstance(v, (str, int, float)):
                    if GENERIC_SECRET_KEYS.match(k) or k in ("password", "private_key", "privateKey"):
                        found[keyname] = str(v)
                else:
                    walk(v, prefix=f"{keyname}.")

    walk(data)
    return found


def scan_files(root: Path) -> Dict[str, Dict[str, str]]:
    files = find_files(root)
    found_all: Dict[str, Dict[str, str]] = {}

    for f in files:
        rel = f.relative_to(root)
        if f.suffix.lower() == ".json":
            found = extract_from_json_file(f)
            if found:
                found_all[str(rel)] = found
            continue

        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            m = ASSIGNMENT_RE.match(line.strip())
            if m:
                key = m.group("key")
                val = m.group("val")
                if GENERIC_SECRET_KEYS.match(key):
                    found_all.setdefault(str(rel), {})[key] = val

    return found_all


def scrub_from_scan(root: Path, scan_results: Dict[str, Dict[str, str]], backup_file: Optional[Path] = None) -> Tuple[Path, Dict[str, Dict[str, str]]]:
    backup: Dict[str, Dict[str, str]] = {}

    for rel_str, secrets in scan_results.items():
        target = root / rel_str
        if not target.exists():
            continue
        if target.suffix.lower() == ".json":
            try:
                content = json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                continue

            def walk_and_replace(obj, prefix=""):
                if isinstance(obj, dict):
                    for k in list(obj.keys()):
                        keyname = f"{prefix}{k}"
                        if keyname in secrets:
                            backup.setdefault(rel_str, {})[keyname] = secrets[keyname]
                            obj[k] = f"[REDACTED_{k}]"
                        else:
                            obj[k] = walk_and_replace(obj[k], prefix=f"{keyname}.")
                    return obj
                elif isinstance(obj, list):
                    return [walk_and_replace(x, prefix=prefix) for x in obj]
                else:
                    return obj

            new_content = walk_and_replace(content)
            target.write_text(json.dumps(new_content, indent=2), encoding="utf-8")
        else:
            try:
                text = target.read_text(encoding="utf-8")
            except Exception:
                continue
            lines = []
            changed = False
            for line in text.splitlines():
                m = ASSIGNMENT_RE.match(line.strip())
                if m:
                    key = m.group("key")
                    if key in secrets:
                        backup.setdefault(rel_str, {})[key] = secrets[key]
                        lines.append(f"{key}=[REDACTED_{key}]")
                        changed = True
                        continue
                lines.append(line)
            if changed:
                target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if backup_file is None:
        downloads = downloads_folder()
        backup_file = downloads / f"obsidian_secrets_backup_{ts}.json"

    # Also modify `run.py` to set USE_POSTGRES and USE_WAITRESS to False for publishing.
    try:
        run_rel = 'run.py'
        run_path = root / run_rel
        if run_path.exists():
            try:
                orig_run = run_path.read_text(encoding='utf-8')
                # Store original content so it can be restored later
                backup.setdefault(run_rel, {})['original_content'] = orig_run
                new_run = orig_run
                # Replace assignments robustly allowing whitespace/comments
                new_run = re.sub(r'(?m)^(\s*USE_POSTGRES\s*=\s*).+$', r'\1False', new_run)
                new_run = re.sub(r'(?m)^(\s*USE_WAITRESS\s*=\s*).+$', r'\1False', new_run)
                if new_run != orig_run:
                    run_path.write_text(new_run, encoding='utf-8')
                    print("Modified run.py: set USE_POSTGRES and USE_WAITRESS to False for publishing")
            except Exception:
                pass
    except Exception:
        pass

    backup_file.write_text(json.dumps(backup, indent=2), encoding="utf-8")
    return backup_file, backup


def restore_from_backup(root: Path, backup_path: Path) -> None:
    try:
        data = json.loads(backup_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Could not read backup file: {e}")
        return

    for rel_str, secrets in data.items():
        target = root / rel_str
        if not target.exists():
            print(f"Skipping {rel_str}: file not found")
            continue
        if target.suffix.lower() == ".json":
            try:
                content = json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                print(f"Skipping JSON {rel_str}: parse error")
                continue

            def walk_and_restore(obj, prefix=""):
                if isinstance(obj, dict):
                    for k in list(obj.keys()):
                        keyname = f"{prefix}{k}"
                        if keyname in secrets:
                            obj[k] = secrets[keyname]
                        else:
                            obj[k] = walk_and_restore(obj[k], prefix=f"{keyname}.")
                    return obj
                elif isinstance(obj, list):
                    return [walk_and_restore(x, prefix=prefix) for x in obj]
                else:
                    return obj

            new_content = walk_and_restore(content)
            target.write_text(json.dumps(new_content, indent=2), encoding="utf-8")
            print(f"Restored secrets in {rel_str}")
        else:
            try:
                text = target.read_text(encoding="utf-8")
            except Exception:
                print(f"Skipping {rel_str}: read error")
                continue
            lines = []
            for line in text.splitlines():
                m = ASSIGNMENT_RE.match(line.strip())
                if m:
                    key = m.group("key")
                    if key in secrets:
                        val = secrets[key]
                        lines.append(f"{key}={val}")
                        continue
                lines.append(line)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"Restored secrets in {rel_str}")


def launch_gui():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext
    except Exception as e:
        print("Tkinter not available:", e)
        return

    class App:
        def __init__(self, master):
            self.master = master
            master.title("Prepare for Publish - Obsidian Scout")
            master.geometry("900x700")

            btn_frame = tk.Frame(master)
            btn_frame.pack(fill=tk.X, padx=8, pady=6)

            self.scan_btn = tk.Button(btn_frame, text="Scan Repository", command=self.scan)
            self.scan_btn.pack(side=tk.LEFT, padx=4)

            self.apply_btn = tk.Button(btn_frame, text="Apply Scrub", command=self.apply, state=tk.DISABLED)
            self.apply_btn.pack(side=tk.LEFT, padx=4)

            self.restore_btn = tk.Button(btn_frame, text="Restore From Backup", command=self.restore)
            self.restore_btn.pack(side=tk.LEFT, padx=4)

            self.quit_btn = tk.Button(btn_frame, text="Quit", command=master.quit)
            self.quit_btn.pack(side=tk.RIGHT, padx=4)

            self.summary = scrolledtext.ScrolledText(master, wrap=tk.WORD)
            self.summary.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

            self.scan_results: Dict[str, Dict[str, str]] = {}
            self.last_backup: Optional[Path] = None

        def scan(self):
            self.summary.delete(1.0, tk.END)
            self.summary.insert(tk.END, "Scanning repository for secrets...\n")
            self.master.update()
            results = scan_files(ROOT)
            self.scan_results = results
            if not results:
                self.summary.insert(tk.END, "No likely secrets found.\n")
                self.apply_btn.config(state=tk.DISABLED)
                return

            self.summary.insert(tk.END, f"Found secrets in {len(results)} file(s):\n\n")
            total_keys = 0
            for rel, kv in sorted(results.items()):
                self.summary.insert(tk.END, f"{rel}:\n")
                for k, v in kv.items():
                    total_keys += 1
                    display = v if len(v) <= 60 else v[:57] + "..."
                    self.summary.insert(tk.END, f"  - {k}: {display}\n")
                self.summary.insert(tk.END, "\n")

            self.summary.insert(tk.END, f"\nTotal potential secret values found: {total_keys}\n")
            self.summary.insert(tk.END, "\nYou can review the list above. Click 'Apply Scrub' to remove these secrets and create a backup in your Downloads folder.\n")
            self.apply_btn.config(state=tk.NORMAL)

        def apply(self):
            if not self.scan_results:
                messagebox.showinfo("Nothing to do", "No scan results to apply.")
                return
            if not messagebox.askyesno("Confirm", "This will replace detected secret values with placeholders and save a backup to your Downloads folder. Continue?"):
                return
            self.summary.insert(tk.END, "\nApplying scrub...\n")
            self.master.update()
            backup_path, backup = scrub_from_scan(ROOT, self.scan_results, None)
            self.last_backup = backup_path
            self.summary.insert(tk.END, f"Done. Backup written to: {backup_path}\n\n")
            self.summary.insert(tk.END, "Summary of changes:\n")
            for rel, kv in sorted(backup.items()):
                self.summary.insert(tk.END, f"{rel}: {len(kv)} key(s) redacted\n")
            self.apply_btn.config(state=tk.DISABLED)

        def restore(self):
            path = filedialog.askopenfilename(title="Select backup JSON", filetypes=[("JSON files","*.json"), ("All files","*.*")])
            if not path:
                return
            try:
                restore_from_backup(ROOT, Path(path))
                messagebox.showinfo("Restore complete", f"Restored secrets from {path}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not restore: {e}")

    root = tk.Tk()
    app = App(root)
    root.mainloop()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare repository for publishing by removing secrets")
    parser.add_argument("--backup", help="Path to write backup file (optional)")
    parser.add_argument("--restore", help="Path to backup file to restore")
    parser.add_argument("--gui", action="store_true", help="Launch a Tkinter GUI to review and apply changes")
    args = parser.parse_args(argv)

    if args.restore:
        backup_path = Path(args.restore)
        if not backup_path.exists():
            print("Backup file not found")
            return 2
        restore_from_backup(ROOT, backup_path)
        return 0

    if args.gui or (len(sys.argv) == 1):
        try:
            launch_gui()
            return 0
        except Exception as e:
            print("GUI failed to launch, falling back to CLI mode:", e)

    if args.backup:
        custom = Path(args.backup)
        scan_results = scan_files(ROOT)
        backup_path, backup = scrub_from_scan(ROOT, scan_results, None)
        shutil.copy(backup_path, custom)
        print(f"Copied backup to {custom}")
        return 0

    scan_results = scan_files(ROOT)
    if not scan_results:
        print("No likely secrets found.")
        return 0
    backup_path, backup = scrub_from_scan(ROOT, scan_results, None)
    print(f"Scrub complete. Backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
prepare_for_publish.py

Utility to remove secrets (API keys, email passwords, VAPID keys, etc.) from the repo
and save them to a timestamped backup JSON in the user's Downloads folder so they can be
restored after publishing.

Usage:
  python app/prepare_for_publish.py           # scan and remove secrets, write backup to Downloads
  python app/prepare_for_publish.py --backup /path/to/backup.json  # use custom backup path
  python app/prepare_for_publish.py --restore /path/to/backup.json # restore secrets from backup

This script looks for common patterns in JSON, .env-style, and Python files. It is conservative
and only replaces values for known keys or likely secret-looking values. It also skips the
`.git` directory and `node_modules` if present.

Assumptions:
- Your local user Downloads folder is available via the OS path for the current user.
- Secrets are stored in JSON files under `instance/` or config files, or as simple key/value pairs.
"""



import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent

# Patterns to look for: map keys to placeholder values and extraction logic
JSON_KEYS = [
    # file path (relative) -> keys to extract
    ("instance/email_config.json", ["password", "username", "api_key", "host"]),
    ("instance/integrity_config.json", ["integrity_password_hash"]),
    ("app_config.json", ["SECRET_KEY", "SECRET", "API_KEY", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY"]),
    ("config/sync_config.json", ["api_key", "token", "secret"]),
]

# Generic key patterns in JSON or env files to scrub if they look like secrets
GENERIC_SECRET_KEYS = re.compile(r".*(api[_-]?key|secret|password|token|vapid).*", re.IGNORECASE)

# Regex for inline assignments in Python or .env style files
ASSIGNMENT_RE = re.compile(r"^(?P<key>[A-Za-z0-9_\-\.]+)\s*[:=]\s*['\"](?P<val>.+?)['\"]\s*$")


def downloads_folder() -> Path:
    # Cross-platform user's Downloads
    home = Path.home()
    # Windows: usually Downloads
    d = home / "Downloads"
    if d.exists():
        return d
    # fallback to home
    return home


def find_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            # Skip runtime-generated VAPID keys file
            try:
                rel = p.relative_to(root)
                if rel.as_posix().lower() == "instance/vapid_keys.json":
                    continue
            except Exception:
                pass
            # skip virtual envs, git, pycache
            if any(part.startswith(".") for part in p.parts):
                # allow files like .env? skip hidden files to be safe
                continue
            if "__pycache__" in p.parts:
                continue
            if ".git" in p.parts:
                continue
            if p.suffix.lower() in {".py", ".json", ".env", ".txt", ".cfg", ".ini"}:
                files.append(p)
    return files


def extract_from_json_file(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    found = {}

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                keyname = f"{prefix}{k}"
                if isinstance(v, (str, int, float)):
                    if GENERIC_SECRET_KEYS.match(k) or k in ("password", "private_key", "privateKey"):
                        found[keyname] = str(v)
                else:
                    walk(v, prefix=f"{keyname}.")

    walk(data)
    return found


def replace_in_json_file(path: Path, replacements: Dict[str, str]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    def walk_and_replace(obj, prefix=""):
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                keyname = f"{prefix}{k}"
                if keyname in replacements:
                    obj[k] = f"[REDACTED_{k}]"
                else:
                    obj[k] = walk_and_replace(obj[k], prefix=f"{keyname}.")
            return obj
        elif isinstance(obj, list):
            return [walk_and_replace(x, prefix=prefix) for x in obj]
        else:
            return obj

    new_data = walk_and_replace(data)
    path.write_text(json.dumps(new_data, indent=2), encoding="utf-8")


def scan_and_scrub(root: Path) -> Tuple[Path, Dict[str, Dict[str, str]]]:
    files = find_files(root)
    backup: Dict[str, Dict[str, str]] = {}

    # Special-case: redact VAPID keys in app_config.json and set generate flag (CLI path)
    try:
        app_cfg_rel = 'app_config.json'
        app_cfg_path = root / app_cfg_rel
        if app_cfg_path.exists():
            try:
                content = json.loads(app_cfg_path.read_text(encoding='utf-8'))
            except Exception:
                content = {}

            orig_priv = content.get('VAPID_PRIVATE_KEY') if isinstance(content, dict) else None
            orig_pub = content.get('VAPID_PUBLIC_KEY') if isinstance(content, dict) else None
            orig_gen = content.get('VAPID_GENERATE_NEW') if isinstance(content, dict) else None
            if orig_priv is not None or orig_pub is not None or orig_gen is not None:
                backup.setdefault(app_cfg_rel, {})['VAPID_PRIVATE_KEY'] = orig_priv
                backup.setdefault(app_cfg_rel, {})['VAPID_PUBLIC_KEY'] = orig_pub
                backup.setdefault(app_cfg_rel, {})['VAPID_GENERATE_NEW'] = orig_gen

            try:
                if not isinstance(content, dict):
                    content = {}
                # Only rewrite if values look non-empty to avoid unnecessary writes
                changed = False
                if content.get('VAPID_PRIVATE_KEY'):
                    content['VAPID_PRIVATE_KEY'] = '[REDACTED_VAPID_PRIVATE_KEY]'
                    changed = True
                if content.get('VAPID_PUBLIC_KEY'):
                    content['VAPID_PUBLIC_KEY'] = '[REDACTED_VAPID_PUBLIC_KEY]'
                    changed = True
                # Ensure generation flag is set so runtime regenerates keys
                if not content.get('VAPID_GENERATE_NEW'):
                    content['VAPID_GENERATE_NEW'] = True
                    changed = True

                if changed:
                    app_cfg_path.write_text(json.dumps(content, indent=2), encoding='utf-8')
                    print(f"Redacted VAPID keys in {app_cfg_path}")
            except Exception as e:
                print(f"Failed to redact VAPID keys in {app_cfg_path}: {e}")

            # Remove from files list so we don't double-process
            try:
                files = [f for f in files if f.relative_to(root).as_posix() != app_cfg_rel]
            except Exception:
                pass
    except Exception as e:
        print(f"VAPID redact pre-step failed: {e}")

    for f in files:
        rel = f.relative_to(root)
        # handle explicit JSON files first
        if f.suffix.lower() == ".json":
            found = extract_from_json_file(f)
            if found:
                backup[str(rel)] = found
                replace_in_json_file(f, {k: v for k, v in found.items()})
                print(f"Scrubbed JSON secrets in {rel}")
            continue

        # handle env / python / cfg files via assignment regex
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        new_lines: List[str] = []
        changed = False
        for line in text.splitlines():
            m = ASSIGNMENT_RE.match(line.strip())
            if m:
                key = m.group("key")
                val = m.group("val")
                if GENERIC_SECRET_KEYS.match(key):
                    backup.setdefault(str(rel), {})[key] = val
                    new_lines.append(f"{key}=[REDACTED_{key}]")
                    changed = True
                    continue
            new_lines.append(line)

        if changed:
            f.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"Scrubbed secrets in {rel}")

    # write backup to Downloads
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    downloads = downloads_folder()
    backup_file = downloads / f"obsidian_secrets_backup_{ts}.json"

    # Also modify `run.py` to set USE_POSTGRES and USE_WAITRESS to False for publishing.
    try:
        run_rel = 'run.py'
        run_path = root / run_rel
        if run_path.exists():
            try:
                orig_run = run_path.read_text(encoding='utf-8')
                backup.setdefault(run_rel, {})['original_content'] = orig_run
                new_run = orig_run
                new_run = re.sub(r'(?m)^(\s*USE_POSTGRES\s*=\s*).+$', r'\1False', new_run)
                new_run = re.sub(r'(?m)^(\s*USE_WAITRESS\s*=\s*).+$', r'\1False', new_run)
                if new_run != orig_run:
                    run_path.write_text(new_run, encoding='utf-8')
                    print("Modified run.py: set USE_POSTGRES and USE_WAITRESS to False for publishing")
            except Exception:
                pass
    except Exception:
        pass

    backup_file.write_text(json.dumps(backup, indent=2), encoding="utf-8")
    print(f"Backup written to {backup_file}")
    return backup_file, backup


def restore_from_backup(root: Path, backup_path: Path) -> None:
    try:
        data = json.loads(backup_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Could not read backup file: {e}")
        return

    for rel_str, secrets in data.items():
        target = root / rel_str
        if not target.exists():
            print(f"Skipping {rel_str}: file not found")
            continue
        # Special-case: restore original `run.py` content if present in backup
        if rel_str == 'run.py':
            if isinstance(secrets, dict) and 'original_content' in secrets:
                try:
                    target.write_text(secrets['original_content'], encoding='utf-8')
                    print(f"Restored secrets in {rel_str}")
                except Exception as e:
                    print(f"Could not restore {rel_str}: {e}")
            else:
                print(f"Skipping run.py: no original content in backup")
            continue
            continue
        if target.suffix.lower() == ".json":
            try:
                content = json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                print(f"Skipping JSON {rel_str}: parse error")
                continue

            def walk_and_restore(obj, prefix=""):
                if isinstance(obj, dict):
                    for k in list(obj.keys()):
                        keyname = f"{prefix}{k}"
                        if keyname in secrets:
                            # restore original value
                            obj[k] = secrets[keyname]
                        else:
                            obj[k] = walk_and_restore(obj[k], prefix=f"{keyname}.")
                    return obj
                elif isinstance(obj, list):
                    return [walk_and_restore(x, prefix=prefix) for x in obj]
                else:
                    return obj

            new_content = walk_and_restore(content)
            target.write_text(json.dumps(new_content, indent=2), encoding="utf-8")
            print(f"Restored secrets in {rel_str}")
        else:
            # assume line-based key=val or key: "val" style
            try:
                text = target.read_text(encoding="utf-8")
            except Exception:
                print(f"Skipping {rel_str}: read error")
                continue
            lines = []
            for line in text.splitlines():
                m = ASSIGNMENT_RE.match(line.strip())
                if m:
                    key = m.group("key")
                    if key in secrets:
                        val = secrets[key]
                        lines.append(f"{key}={val}")
                        continue
                lines.append(line)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"Restored secrets in {rel_str}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare repository for publishing by removing secrets")
    parser.add_argument("--backup", help="Path to write backup file (optional)")
    parser.add_argument("--restore", help="Path to backup file to restore")
    args = parser.parse_args(argv)

    if args.restore:
        backup_path = Path(args.restore)
        if not backup_path.exists():
            print("Backup file not found")
            return 2
        restore_from_backup(ROOT, backup_path)
        return 0

    # create backup in downloads unless custom provided
    if args.backup:
        custom = Path(args.backup)
        # run scan but write to a temp then copy
        bfile, _ = scan_and_scrub(ROOT)
        shutil.copy(bfile, custom)
        print(f"Copied backup to {custom}")
        return 0

    scan_and_scrub(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
