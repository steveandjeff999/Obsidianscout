#!/usr/bin/env python3
"""
Remote updater helper - downloads a ZIP from a URL, runs the repository update logic,
edits run.py to toggle USE_WAITRESS and restarts the server.

This script is intended to be launched locally (on the server being updated) by
the `/api/sync/update` endpoint. It performs best-effort process management and
will attempt to leave the updated server running.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import requests
except Exception:
    requests = None


def download_zip(url: str, dest: Path) -> Path:
    if requests is None:
        raise RuntimeError('requests is required to download the ZIP')

    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(1024 * 64):
            if chunk:
                f.write(chunk)
    return dest


def set_use_waitress_in_run(run_py: Path, use_waitress: bool):
    # Replace the line that assigns USE_WAITRESS
    text = run_py.read_text()
    new_line = f"USE_WAITRESS = {str(bool(use_waitress))}  # Updated by remote_updater"
    import re
    pattern = re.compile(r"^USE_WAITRESS\s*=.*$", re.M)
    if pattern.search(text):
        text = pattern.sub(new_line, text)
    else:
        # Fallback: insert near top
        text = new_line + '\n' + text
    run_py.write_text(text)


def start_server(run_py_path: Path, port: int) -> int:
    env = os.environ.copy()
    env['PORT'] = str(port)
    # Start the server as a background process
    log_dir = Path.cwd() / 'instance'
    log_dir.mkdir(parents=True, exist_ok=True)
    out = open(log_dir / 'server_update_stdout.log', 'ab')
    err = open(log_dir / 'server_update_stderr.log', 'ab')
    proc = subprocess.Popen([sys.executable, str(run_py_path)], env=env, stdout=out, stderr=err, close_fds=True)
    return proc.pid


def kill_other_python_processes(keep_pids: list[int]):
    # Cross-platform process management
    killed = []
    
    # On Windows, we'll use tasklist and taskkill
    if os.name == 'nt':
        try:
            import subprocess
            # Get list of python processes
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python*', '/FO', 'CSV'], 
                                  capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if line.strip():
                        parts = line.strip('"').split('","')
                        if len(parts) >= 2:
                            try:
                                pid = int(parts[1])
                                if pid not in keep_pids and pid != os.getpid():
                                    # Try to terminate the process
                                    subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                                                 capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                                    killed.append(pid)
                            except (ValueError, subprocess.SubprocessError):
                                continue
        except Exception:
            pass  # If Windows process management fails, continue without killing
    else:
        # Unix/Linux process management (original code)
        try:
            my_uid = os.getuid()
            proc_dir = Path('/proc')
            for p in proc_dir.iterdir():
                if not p.name.isdigit():
                    continue
                pid = int(p.name)
                if pid in keep_pids or pid == os.getpid():
                    continue
                try:
                    # Read cmdline
                    cmdline = (p / 'cmdline').read_bytes().decode('utf-8', errors='ignore')
                    if 'python' in cmdline.lower():
                        # Check ownership
                        try:
                            uid = int((p / 'status').read_text().split('Uid:')[1].strip().split()[0])
                        except Exception:
                            uid = None
                        if uid is not None and uid != my_uid:
                            continue
                        try:
                            os.kill(pid, signal.SIGTERM)
                            killed.append(pid)
                        except Exception:
                            try:
                                os.kill(pid, signal.SIGKILL)
                                killed.append(pid)
                            except Exception:
                                pass
                except Exception:
                    continue
        except Exception:
            pass  # If Unix process management fails, continue without killing
    
    return killed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip-url', dest='zip_url', required=True)
    parser.add_argument('--use-waitress', dest='use_waitress', action='store_true')
    parser.add_argument('--port', dest='port', type=int, default=8080)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    run_py = repo_root / 'run.py'

    # Download zip
    tmpdir = Path(tempfile.mkdtemp(prefix='obs_remote_update_'))
    zip_path = tmpdir / 'release.zip'
    try:
        print(f"Downloading update from {args.zip_url} to {zip_path}...", flush=True)
        download_zip(args.zip_url, zip_path)

        # Backup sync server configuration before update
        print("Backing up sync server configuration...", flush=True)
        try:
            backup_result = subprocess.run([
                sys.executable, 'sync_config_manager.py', '--backup'
            ], capture_output=True, text=True, cwd=repo_root)
            if backup_result.returncode == 0:
                print("✅ Sync config backed up successfully", flush=True)
            else:
                print(f"⚠️  Sync config backup warning: {backup_result.stderr}", flush=True)
        except Exception as e:
            print(f"⚠️  Could not backup sync config: {e}", flush=True)

        # Run perform_update from update_from_github_file
        sys.path.insert(0, str(repo_root))
        from update_from_github_file import perform_update

        print("Applying update...", flush=True)
        # Preserve sync server configuration by ensuring instance folder is preserved
        rc = perform_update(str(zip_path), is_zip=True, force=True, repo_root=repo_root)
        print(f"perform_update returned {rc}", flush=True)
        
        if rc != 0:
            print(f"WARNING: Update returned non-zero exit code {rc}", flush=True)

        # Verify sync server configuration is preserved
        print("Verifying sync server configuration...", flush=True)
        try:
            verify_result = subprocess.run([
                sys.executable, 'sync_config_manager.py', '--verify'
            ], capture_output=True, text=True, cwd=repo_root)
            if verify_result.returncode == 0:
                print("✅ Sync server configuration verified", flush=True)
                print(verify_result.stdout, flush=True)
            else:
                print(f"⚠️  Sync config verification issue: {verify_result.stderr}", flush=True)
        except Exception as e:
            print(f"⚠️  Could not verify sync config: {e}", flush=True)

        # Edit run.py
        print(f"Setting USE_WAITRESS={args.use_waitress} in run.py", flush=True)
        set_use_waitress_in_run(run_py, args.use_waitress)

        # Start server
        print(f"Starting server on port {args.port}...", flush=True)
        child_pid = start_server(run_py, args.port)
        print(f"Started server pid={child_pid}", flush=True)

        # Give server time to start
        time.sleep(5)

        # Kill other python processes
        print("Killing other python processes (best-effort)...", flush=True)
        killed = kill_other_python_processes([child_pid, os.getpid()])
        print(f"Killed PIDs: {killed}", flush=True)

        print("Updater finished; exiting.", flush=True)

    except Exception as e:
        print(f"Updater error: {e}", flush=True)
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass


if __name__ == '__main__':
    main()
