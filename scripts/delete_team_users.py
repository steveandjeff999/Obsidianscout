"""
Script to delete or deactivate all users for a given scouting team number.

Usage examples (PowerShell):
# Dry run (list users that would be affected)
python .\scripts\delete_team_users.py --team 9999 --mode dry-run

# Soft-delete (deactivate) users after confirmation
python .\scripts\delete_team_users.py --team 9999 --mode soft

# Permanent delete (hard delete) users after explicit confirmation
python .\scripts\delete_team_users.py --team 9999 --mode hard

This script must be run from the repository root and will load the Flask app
context so it can safely query and modify the database. It will NOT delete users
with the 'superadmin' role.
"""
import argparse
import sys
import os

# Ensure project root is on sys.path so `from app import ...` works when running
# this script directly (PowerShell/CLI). This makes the script resilient to
# being executed from different CWDs or by tools that don't add the repo root
# to PYTHONPATH.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from app import create_app, db
from app.models import User, DatabaseChange
from datetime import datetime, timezone


def confirm(prompt: str) -> bool:
    try:
        resp = input(prompt + "\nType YES to confirm: ")
        return resp.strip() == 'YES'
    except KeyboardInterrupt:
        print('\nAborted by user')
        return False


DEFAULT_TEAM = 9999  # Set to an integer (e.g. 9999) if you want to hard-code the team in the script
DEFAULT_MODE = 'hard'  # Set to 'dry-run', 'soft', or 'hard' to hard-code default delete mode


def main():
    parser = argparse.ArgumentParser(description='Delete or deactivate all users for a scouting team')
    parser.add_argument('--team', type=int, required=False, default=None,
                        help='Scouting team number whose users should be affected (overrides DEFAULT_TEAM or env DELETE_TEAM)')
    # --delete-type is an alias for --mode for clarity; -m is a short alias as well
    # default is left as None so we can fall back to DEFAULT_MODE or DELETE_MODE env var
    parser.add_argument('-m', '--mode', '--delete-type', dest='mode',
                        choices=['dry-run', 'soft', 'hard'], default=None,
                        help="dry-run (list), soft (deactivate), hard (permanent delete).\n"
                             "You may use --mode, --delete-type, or -m. If omitted, the script will use DEFAULT_MODE or the DELETE_MODE env var.")
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt (use with caution)')
    args = parser.parse_args()

    # Determine team number: CLI arg > DEFAULT_TEAM > DELETE_TEAM env var > prompt
    team_from_arg = args.team
    team_from_env = None
    try:
        env_val = os.environ.get('DELETE_TEAM')
        if env_val:
            team_from_env = int(env_val)
    except Exception:
        team_from_env = None

    team = team_from_arg or DEFAULT_TEAM or team_from_env
    # Determine mode: CLI arg > DEFAULT_MODE > DELETE_MODE env var
    mode_from_arg = args.mode
    mode_from_env = None
    try:
        env_mode = os.environ.get('DELETE_MODE')
        if env_mode in ('dry-run', 'soft', 'hard'):
            mode_from_env = env_mode
    except Exception:
        mode_from_env = None

    mode = mode_from_arg or DEFAULT_MODE or mode_from_env
    skip_confirm = args.yes

    if team is None:
        # Prompt interactively if no team specified
        try:
            resp = input('Enter scouting team number to affect: ').strip()
            team = int(resp)
        except Exception:
            print('No valid team number provided; aborting.')
            return

    app = create_app()
    with app.app_context():

        query = User.query.filter_by(scouting_team_number=team)
        users = query.all()

        if not users:
            print(f"No users found for scouting team {team}.")
            return

        # Exclude superadmin users from destructive actions
        non_super_users = [u for u in users if not u.has_role('superadmin')]
        super_users = [u for u in users if u.has_role('superadmin')]

        print(f"Found {len(users)} users for team {team}: {len(non_super_users)} non-superadmin, {len(super_users)} superadmin (will be skipped)")
        for u in users:
            roles = ','.join([r.name for r in u.roles])
            print(f"  - id={u.id} username={u.username} roles=[{roles}] active={u.is_active}")

        if mode == 'dry-run':
            print('\nDry-run mode, no changes made.')
            return

        if mode == 'soft':
            prompt = f"About to DEACTIVATE (soft-delete) {len(non_super_users)} users for team {team}."
        else:
            prompt = f"About to PERMANENTLY DELETE {len(non_super_users)} users for team {team}. THIS ACTION IS IRREVERSIBLE."

        if not skip_confirm:
            if not confirm(prompt):
                print('Confirmation not provided; aborting.')
                return

        affected = 0
        for u in non_super_users:
            username = u.username
            if mode == 'soft':
                u.is_active = False
                if hasattr(u, 'updated_at'):
                    try:
                        u.updated_at = datetime.now(timezone.utc)
                    except Exception:
                        pass
                # Log change
                try:
                    DatabaseChange.log_change(
                        table_name='user',
                        record_id=u.id,
                        operation='soft_delete',
                        new_data={'id': u.id, 'username': u.username, 'is_active': u.is_active},
                        server_id='local'
                    )
                except Exception as e:
                    print(f'Warning: Failed to log soft delete for {username}: {e}')
                affected += 1
            else:  # hard delete
                print(f"Deleting user id={u.id} username={username}...")
                # Clear role associations to avoid FK/association issues
                try:
                    if hasattr(u, 'roles') and u.roles:
                        u.roles.clear()
                        db.session.flush()
                except Exception as e:
                    print(f"Warning: Failed to clear roles for {username}: {e}")
                try:
                    DatabaseChange.log_change(
                        table_name='user',
                        record_id=u.id,
                        operation='delete',
                        old_data={'id': u.id, 'username': u.username, 'scouting_team_number': u.scouting_team_number, 'is_active': u.is_active},
                        server_id='local'
                    )
                except Exception as e:
                    print(f'Warning: Failed to log hard delete for {username}: {e}')

                try:
                    db.session.delete(u)
                    # Commit per-user so we can see immediate failures and continue
                    db.session.commit()
                    affected += 1
                    print(f"Deleted user id={u.id} username={username}")
                except Exception as e:
                    print(f"Error deleting {username}: {e}")
                    db.session.rollback()

        try:
            db.session.commit()
        except Exception as e:
            print(f'Error committing database changes: {e}')
            db.session.rollback()
            return

        print(f"Completed: {mode} for {affected} users on team {team}.")


if __name__ == '__main__':
    main()
