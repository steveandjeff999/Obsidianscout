#!/usr/bin/env python3
"""Unstamp Alembic migrations for selected binds.

This script stamps the target DB(s) to 'base' (effectively marking all migrations as unapplied).
Use with care. By default, it operates on all binds.

Usage:
  python -m tools.unstamp_alembic_all [--binds users pages misc] [--yes] [--dry-run] [--no-backup]

"""
import argparse
import os
import sys
import shutil
from datetime import datetime

from app import create_app
from app import db as flask_db
from tools.autogen_migration_gui import run_alembic_stamp


def log(msg):
    print(f"[{datetime.utcnow().isoformat()}] {msg}")


def get_engine_for_bind(flask_db, binds, name):
    target_bind = None if name == 'default' else name
    try:
        engine = flask_db.get_engine(bind=target_bind)
    except Exception:
        engine = None
        try:
            engine = flask_db.engines.get(target_bind) or flask_db.engines.get(None)
        except Exception:
            engine = None
    if engine is None:
        try:
            uri = binds.get(name)
            if uri:
                log(f"Creating engine for bind {name} from URI: {uri}")
                from sqlalchemy import create_engine
                engine = create_engine(uri)
        except Exception as e:
            log(f"Failed to create engine for bind {name}: {e}")
            engine = None
    return engine


def main():
    parser = argparse.ArgumentParser(description='Unstamp alembic version to base for selected binds')
    parser.add_argument('--binds', nargs='*', default=None, help='List of binds to unstamp (default: all)')
    parser.add_argument('--yes', action='store_true', help='Do not prompt for confirmation')
    parser.add_argument('--dry-run', action='store_true', help='Show actions without modifying DBs')
    parser.add_argument('--no-backup', action='store_true', help='Do not backup DBs before stamping')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        binds_cfg = {'default': app.config.get('SQLALCHEMY_DATABASE_URI')}
        binds_cfg.update(app.config.get('SQLALCHEMY_BINDS') or {})
        selected = args.binds or list(binds_cfg.keys())

        if not args.yes:
            print('About to stamp the following binds to base (mark as unapplied):', selected)
            print('This will modify alembic tracking for these databases (destructive).')
            print('Backups will be created unless --no-backup is specified.')
            proceed = input('Continue? (y/N): ').lower().strip() == 'y'
            if not proceed:
                print('Aborted.')
                return

        if not args.no_backup:
            ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            backup_dir = os.path.join(app.instance_path, 'backup', ts)
            os.makedirs(backup_dir, exist_ok=True)
            for f in os.listdir(app.instance_path):
                if f.endswith('.db'):
                    src = os.path.join(app.instance_path, f)
                    dst = os.path.join(backup_dir, f)
                    try:
                        shutil.copy2(src, dst)
                        log(f'Backed up {src} -> {dst}')
                    except Exception as e:
                        log(f'Warning: could not backup {src}: {e}')

        for name in selected:
            if name not in binds_cfg:
                log(f'Bind {name} is not configured, skipping')
                continue
            engine = get_engine_for_bind(flask_db, binds_cfg, name)
            if not engine:
                log(f'Could not resolve engine for bind {name}; skipping')
                continue
            log(f'Preparing to stamp bind: {name} ({getattr(engine, "url", None)})')
            try:
                from sqlalchemy import inspect
                ins = inspect(engine)
                if not ins.get_table_names():
                    log(f'No tables found for bind {name} - skipping')
                    continue
                # If alembic_version not present, we can still run stamp base
                if args.dry_run:
                    log(f'(Dry) Would run alembic stamp base for bind {name}')
                else:
                    stamped, err = run_alembic_stamp(engine, revision='base')
                    if stamped:
                        log(f'Stamped {name} to base successfully')
                    else:
                        log(f'Failed to stamp {name}: {err}')
            except Exception as e:
                log(f'Error processing bind {name}: {e}')

if __name__ == '__main__':
    main()
