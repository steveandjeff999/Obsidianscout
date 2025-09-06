import sqlite3
import os

def list_tables(path):
    print(f"\nChecking: {path}")
    if not os.path.exists(path):
        print("  File not found")
        return
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        rows = cur.fetchall()
        names = [r[0] for r in rows]
        if not names:
            print("  No tables found")
        else:
            for n in sorted(names):
                print(f"  {n}")
        conn.close()
    except Exception as e:
        print("  ERROR:", e)

for p in ('instance/scouting.db', 'instance/users.db'):
    list_tables(p)
