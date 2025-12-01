#!/usr/bin/env python3
"""Run autogenerate and apply migrations across all configured binds non-interactively.

This script calls the logic in tools.apply_alembic_upgrades.apply_upgrades_for_binds
with safe defaults and is meant to be called during deployment or startup scripts.

Usage:
    python -m tools.run_autoupdate

Optional environment args in invocation may be used to pass CLI parameters.
"""
import sys
from app import create_app
from tools.apply_alembic_upgrades import apply_upgrades_for_binds


def main():
    app = create_app()
    binds = list({'default': app.config.get('SQLALCHEMY_DATABASE_URI')}.keys()) + list((app.config.get('SQLALCHEMY_BINDS') or {}).keys())
    print('Starting autoupdate for binds:', binds)
    # Safe defaults: backup enabled, not dry-run, auto-generate, auto-stamp and auto-delete enabled
    apply_upgrades_for_binds(app, binds, no_backup=False, dry_run=False, log_widget=None, auto_stamp=True, auto_delete=True, auto_generate=True)


if __name__ == '__main__':
    main()
