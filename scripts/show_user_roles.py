import sqlite3
import os


def show_user_roles(db_path):
    print(f"\nDB: {db_path}")
    if not os.path.exists(db_path):
        print("  File not found")
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check if user_roles table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_roles'")
        if not cur.fetchone():
            print("  user_roles table not present")
            conn.close()
            return

        # Try to get user_roles rows
        try:
            cur.execute("SELECT user_id, role_id FROM user_roles")
            rows = cur.fetchall()
        except Exception as e:
            print(f"  Error reading user_roles: {e}")
            conn.close()
            return

        print(f"  user_roles count: {len(rows)}")
        if not rows:
            conn.close()
            return

        # Attempt to join with user and role tables to show names
        # If those tables don't exist, just print raw ids
        has_user = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user'").fetchone()
        has_role = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='role'").fetchone()

        if has_user and has_role:
            try:
                cur.execute("SELECT ur.user_id, u.username, ur.role_id, r.name FROM user_roles ur LEFT JOIN user u ON ur.user_id = u.id LEFT JOIN role r ON ur.role_id = r.id")
                joined = cur.fetchall()
                for ur in joined:
                    print(f"  user_id={ur[0]} username={ur[1]} role_id={ur[2]} role_name={ur[3]}")
            except Exception as e:
                print(f"  Could not join user/role: {e}")
                for ur in rows[:20]:
                    print(f"  user_id={ur[0]} role_id={ur[1]}")
        else:
            for ur in rows[:50]:
                print(f"  user_id={ur[0]} role_id={ur[1]}")
            if len(rows) > 50:
                print(f"  ... {len(rows)-50} more rows")

        conn.close()
    except Exception as e:
        print(f"  ERROR: {e}")


if __name__ == '__main__':
    for p in ('instance/scouting.db', 'instance/users.db'):
        show_user_roles(p)
