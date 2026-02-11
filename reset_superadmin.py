#!/usr/bin/env python3
"""
Create or reset the superadmin user for Obsidianscout.

This script will ensure there is a user with username "superadmin",
scouting_team_number 0, and password "0" and that the user has the
`superadmin` role. It will detect if PostgreSQL is configured and
start the app in PostgreSQL mode when appropriate. You can also force
Postgres with `--use-postgres`.
"""
import sys
import os
import json
import argparse

# Ensure repo root is on path so imports work when running this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Role


def reset_superadmin_user():
    print("Resetting superadmin user...")

    # Ensure the superadmin role exists
    super_role = Role.query.filter_by(name='superadmin').first()
    if not super_role:
        print("Creating 'superadmin' role...")
        super_role = Role(name='superadmin', description='Limited superadmin role for user management')
        db.session.add(super_role)
        db.session.commit()

    username = 'superadmin'
    password = '0'

    user = User.query.filter_by(username=username).first()

    if user:
        print(f"User '{username}' exists. Resetting password, team number, and roles...")
        user.set_password(password)
        user.scouting_team_number = 0
        user.is_active = True
        # Ensure only has superadmin role (clear others)
        user.roles = []
        user.roles.append(super_role)
    else:
        print(f"Creating new user '{username}'...")
        user = User(username=username, email=None, scouting_team_number=0)
        user.set_password(password)
        user.roles.append(super_role)
        db.session.add(user)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    print("\nSuperadmin user is ready:")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print("  scouting_team_number: 0")


def detect_postgres_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'postgres_config.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as fh:
                cfg = json.load(fh)
            # minimal validation
            if cfg.get('host') and cfg.get('database'):
                return True
        except Exception:
            pass
    return False


def main():
    p = argparse.ArgumentParser(description='Reset or create the superadmin user')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--use-postgres', action='store_true', help='Force using PostgreSQL (if configured)')
    group.add_argument('--use-sqlite', action='store_true', help='Force using SQLite')
    args = p.parse_args()

    # Decide which DB(s) to use. Explicit flags take precedence. If no flags,
    # run against both SQLite and PostgreSQL (Postgres attempted only if available).
    if args.use_sqlite:
        targets = ['sqlite']
    elif args.use_postgres:
        targets = ['postgres']
    else:
        targets = ['sqlite', 'postgres']

    for target in targets:
        if target == 'sqlite':
            print("Starting app for SQLite...")
            app = create_app(use_postgres=False)
        else:
            # Attempt Postgres; skip gracefully if not configured or fails to start
            if not detect_postgres_config():
                print("Postgres config not found; skipping Postgres run.")
                continue
            print("Starting app for PostgreSQL...")
            try:
                app = create_app(use_postgres=True)
            except Exception as e:
                print(f"Failed to create app with Postgres: {e}")
                continue

        try:
            with app.app_context():
                reset_superadmin_user()
        except Exception as e:
            print(f"Error while resetting superadmin for {target}: {e}")
        finally:
            try:
                db.session.remove()
            except Exception:
                pass


if __name__ == '__main__':
    main()
