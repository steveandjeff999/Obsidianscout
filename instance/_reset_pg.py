"""Temporary script: drop and recreate PG databases with fresh schema."""
import os, sys, json, platform

# WMI workaround for Python 3.14
if os.name == 'nt' and hasattr(platform, '_wmi_query'):
    platform._wmi_query = lambda *a, **k: (_ for _ in ()).throw(OSError('disabled'))
    platform._wmi = None

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

cfg = json.load(open('config/postgres_config.json'))
import psycopg2

pw = cfg.get('superuser_password', '')
conn = psycopg2.connect(host=cfg['host'], port=cfg['port'], user='postgres', password=pw, dbname='postgres')
conn.autocommit = True
cur = conn.cursor()

for db_name in ['obsidian_scout', 'obsidian_scout_users', 'obsidian_scout_pages', 'obsidian_scout_misc']:
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid != pg_backend_pid()", (db_name,)
    )
    cur.execute(f'DROP DATABASE IF EXISTS {db_name}')
    cur.execute(f'CREATE DATABASE {db_name} OWNER "{cfg["user"]}"')
    print(f'Recreated {db_name}')

cur.close()
conn.close()

# Also remove migration flag
flag = os.path.join('instance', '.pg_initial_migration_done')
if os.path.exists(flag):
    os.remove(flag)
    print('Removed migration flag')

print('Done – databases are empty and ready.')
