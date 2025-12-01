#!/usr/bin/env python3
"""Run autoupdate (autogenerate + apply) and then start the app.

This is a convenience wrapper that ensures migrations are applied before the app starts.
"""
import argparse
import subprocess
import sys
from app import create_app
from tools.apply_alembic_upgrades import apply_upgrades_for_binds


def run_autoupdate_and_start(no_backup=False, dry_run=False, no_autogen=False, extra_args=None):
    app = create_app()
    binds = list({'default': app.config.get('SQLALCHEMY_DATABASE_URI')}.keys()) + list((app.config.get('SQLALCHEMY_BINDS') or {}).keys())
    apply_upgrades_for_binds(app, binds, no_backup=no_backup, dry_run=dry_run, log_widget=None, auto_stamp=True, auto_delete=True, auto_generate=not no_autogen)

    # Start the app in a subprocess to preserve process isolation
    args = [sys.executable, 'run.py']
    if extra_args:
        args += extra_args
    subprocess.run(args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Autoupdate and start the app')
    parser.add_argument('--no-backup', action='store_true', help='Do not backup DBs before running autoupdate')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (do not modify DBs)')
    parser.add_argument('--no-autogen', action='store_true', help='Do not run autogeneration')
    parser.add_argument('--no-start', action='store_true', help='Run autoupdate only and do not start the server')
    parser.add_argument('extra', nargs='*', help='Extra args passed to run.py when starting the server')
    args = parser.parse_args()
    run_autoupdate_and_start(no_backup=args.no_backup, dry_run=args.dry_run, no_autogen=args.no_autogen, extra_args=args.extra if not args.no_start else None)
