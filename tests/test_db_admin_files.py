import os
from app import create_app
from app.utils.instance_db import list_instance_db_files, backup_db_file


def test_list_and_backup_retention(tmp_path):
    app = create_app({'TESTING': True, 'DB_FILE_MANAGEMENT_ENABLED': True, 'DB_BACKUP_RETENTION': 3})
    # Use tmp_path as instance_path
    app.instance_path = str(tmp_path)
    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Create sample DB files
    db1 = tmp_path / 'one.db'
    db2 = tmp_path / 'two.db'
    db1.write_bytes(b'')
    db2.write_bytes(b'')

    with app.app_context():
        files = list_instance_db_files()
        names = [f['name'] for f in files]
        assert 'one.db' in names
        assert 'two.db' in names

        # Create multiple backups to test retention
        first_backup = backup_db_file('one.db')
        assert os.path.exists(first_backup)

        for i in range(5):
            backup_db_file('one.db')

        backup_dir = os.path.join(app.instance_path, 'backup')
        backups = [p for p in os.listdir(backup_dir) if p.startswith('one.db.') and p.endswith('.bak')]
        # Retention set to 3 in test config, so should be <= 3
        assert len(backups) <= 3


def test_enable_crsqlite_not_configured(tmp_path):
    app = create_app({'TESTING': True, 'DB_FILE_MANAGEMENT_ENABLED': True})
    app.instance_path = str(tmp_path)
    os.makedirs(app.instance_path, exist_ok=True)

    with app.app_context():
        res = None
        try:
            res = __import__('app.utils.database_manager', fromlist=['concurrent_db_manager']).concurrent_db_manager.enable_crsqlite_on_bind(None)
        except Exception as e:
            res = {'success': False, 'message': str(e)}
        # Since we don't have a CR-SQLite DLL in the test instance, expect failure message
        assert isinstance(res, dict)
        assert res.get('success') in (False, None)
        assert 'CR-SQLite' in (res.get('message') or '') or 'not configured' in (res.get('message') or '').lower()


def test_get_connection_stats_returns_keys(tmp_path):
    app = create_app({'TESTING': True})
    app.instance_path = str(tmp_path)
    os.makedirs(app.instance_path, exist_ok=True)

    with app.app_context():
        manager = __import__('app.utils.database_manager', fromlist=['concurrent_db_manager']).concurrent_db_manager
        stats = manager.get_connection_stats()
        assert isinstance(stats, dict)
        assert 'pool_size' in stats and 'checked_in' in stats and 'checked_out' in stats and 'overflow' in stats
