import sqlite3
import os

paths = ['instance/scouting.db', 'instance/users.db']

for p in paths:
    print(f"\nDB: {p}")
    if not os.path.exists(p):
        print('  File not found')
        continue
    conn = sqlite3.connect(p)
    cur = conn.cursor()
    # Check for user by id=1010
    try:
        cur.execute("SELECT * FROM user WHERE id = 1010")
        rows = cur.fetchall()
        if rows:
            print('  Found user with id=1010:')
            for r in rows:
                print('   ', r)
        else:
            print('  No user with id=1010')
    except Exception as e:
        print('  user table check error:', e)
    # Check for username containing 1010
    try:
        cur.execute("SELECT * FROM user WHERE username LIKE '%1010%'")
        rows = cur.fetchall()
        if rows:
            print("  Found username like '1010':")
            for r in rows:
                print('   ', r)
        else:
            print("  No username like '1010'")
    except Exception as e:
        print('  username LIKE check error:', e)
    # If user_roles exists, list roles for id 1010
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_roles'")
        if cur.fetchone():
            cur.execute('SELECT user_id, role_id FROM user_roles WHERE user_id = 1010')
            rows = cur.fetchall()
            print('  user_roles rows for user_id=1010:', rows)
        else:
            print('  user_roles table not present')
    except Exception as e:
        print('  user_roles check error:', e)
    conn.close()
