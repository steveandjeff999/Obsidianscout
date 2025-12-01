"""
Migrate selected user preferences from file-backed `instance/user_prefs.json` into the users DB table.

Usage:
  python tools/migrate_user_prefs_to_db.py --apply  # to update DB and remove migrated entries
  python tools/migrate_user_prefs_to_db.py         # dry-run to preview changes

This focuses on 'only_password_reset_emails' preference.
"""

import argparse
import os
import sys
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
from app import create_app, db
from app.utils import user_prefs as user_prefs_util


def migrate(remove_after=False):
    app = create_app()
    with app.app_context():
        prefs = user_prefs_util.load_prefs()
        changes = []
        for uname, up in prefs.items():
            if not isinstance(up, dict):
                continue
            if 'only_password_reset_emails' in up:
                # Find user
                from app.models import User
                u = User.query.filter_by(username=uname).first()
                if not u:
                    changes.append((uname, 'user not found'))
                    continue
                val = bool(up.get('only_password_reset_emails', False))
                if getattr(u, 'only_password_reset_emails', None) != val:
                    changes.append((uname, u.id, getattr(u, 'only_password_reset_emails', None), val))
                    if remove_after:
                        try:
                            u.only_password_reset_emails = val
                            db.session.add(u)
                            db.session.commit()
                            del up['only_password_reset_emails']
                        except Exception:
                            db.session.rollback()
                            changes.append((uname, 'apply_failed'))
                else:
                    changes.append((uname, 'no_change'))

        # If removal requested, write back the prefs file with removed entries
        if remove_after:
            user_prefs_util.save_prefs(prefs)

        return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Apply changes to DB and remove JSON entries')
    args = parser.parse_args()
    changes = migrate(remove_after=args.apply)
    for c in changes:
        print(c)
    print('Done.')


if __name__ == '__main__':
    main()
