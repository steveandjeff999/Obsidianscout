#!/usr/bin/env python3
"""
SQLite <-> PostgreSQL Migration Utility for Obsidian Scout.

Provides fully automated, bidirectional data migration between the SQLite
database files used in development/portable mode and a PostgreSQL server.

Usage (standalone):
    python -m app.utils.db_migrate --direction sqlite-to-postgres
    python -m app.utils.db_migrate --direction postgres-to-sqlite

Usage (from code):
    from app.utils.db_migrate import migrate_sqlite_to_postgres, migrate_postgres_to_sqlite
    migrate_sqlite_to_postgres()   # push local data → PG
    migrate_postgres_to_sqlite()   # pull PG data → local SQLite
"""

import os
import sys
import json
import argparse
import sqlite3
from datetime import datetime, timezone

try:
    from sqlalchemy import create_engine, inspect, text, MetaData, Column
    from sqlalchemy.exc import OperationalError, ProgrammingError
    from sqlalchemy import types as sa_types
except ImportError:
    print("ERROR: SQLAlchemy is required. pip install sqlalchemy")
    sys.exit(1)

# ---------------------------------------------------------------------------
# SQLite  →  PostgreSQL type translation
# ---------------------------------------------------------------------------
# When we reflect a SQLite schema, column types are often generic names
# (BLOB, DATETIME, etc.) that PostgreSQL doesn't recognise.  We create
# translated copies of every table so that CREATE TABLE succeeds on PG.

_SQLITE_TO_PG_TYPE_MAP = {
    'BLOB':       sa_types.LargeBinary,
    'DATETIME':   sa_types.DateTime,
    'TIMESTAMP':  sa_types.DateTime,
    'BOOLEAN':    sa_types.Boolean,
    'INTEGER':    sa_types.BigInteger,
    'REAL':       sa_types.Float,
    'NUMERIC':    sa_types.Numeric,
}


def _translate_column_type(col_type):
    """Convert a reflected SQLite column type to one PostgreSQL understands."""
    type_name = type(col_type).__name__.upper()
    # Also check the compiled / generic name
    try:
        type_str = str(col_type).upper()
    except Exception:
        type_str = type_name
    for sqlite_name, pg_cls in _SQLITE_TO_PG_TYPE_MAP.items():
        if sqlite_name in type_name or sqlite_name in type_str:
            return pg_cls()
    return col_type

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
INSTANCE_DIR = os.path.join(PROJECT_ROOT, 'instance')

# Map of bind_key -> SQLite filename
SQLITE_DB_MAP = {
    None:    'scouting.db',   # default / main
    'users': 'users.db',
    'pages': 'pages.db',
    'misc':  'misc.db',
}


def _sqlite_uri(db_file: str) -> str:
    return 'sqlite:///' + os.path.join(INSTANCE_DIR, db_file)


def _load_pg_config() -> dict:
    """Load PostgreSQL connection details (mirrors postgres_manager._load_config)."""
    defaults = {
        "host": "localhost",
        "port": 5432,
        "user": "obsidian_scout",
        "password": "obsidian_scout_pass",
        "database": "obsidian_scout",
        "database_users": "obsidian_scout_users",
        "database_pages": "obsidian_scout_pages",
        "database_misc": "obsidian_scout_misc",
    }
    cfg_path = os.path.join(PROJECT_ROOT, 'config', 'postgres_config.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r') as f:
                file_cfg = json.load(f)
            defaults.update({k: v for k, v in file_cfg.items() if v is not None})
        except Exception:
            pass
    # Env overrides
    for env_key, cfg_key in (("POSTGRES_HOST", "host"), ("POSTGRES_PORT", "port"),
                              ("POSTGRES_USER", "user"), ("POSTGRES_PASSWORD", "password"),
                              ("POSTGRES_DB", "database")):
        val = os.environ.get(env_key)
        if val:
            defaults[cfg_key] = int(val) if cfg_key == "port" else val
    return defaults


def _pg_uri(pg_cfg: dict, db_key: str | None = None) -> str:
    """Build a PostgreSQL URI for the given bind key."""
    key_map = {
        None:    "database",
        "users": "database_users",
        "pages": "database_pages",
        "misc":  "database_misc",
    }
    db_name = pg_cfg[key_map[db_key]]
    return f"postgresql://{pg_cfg['user']}:{pg_cfg['password']}@{pg_cfg['host']}:{pg_cfg['port']}/{db_name}"


def _get_table_order(engine):
    """Return tables topologically sorted so FK dependencies are satisfied."""
    meta = MetaData()
    meta.reflect(bind=engine)
    # sorted_tables respects FK ordering
    return meta.sorted_tables


def _copy_tables(src_engine, dst_engine, bind_key: str | None, direction: str):
    """
    Copy every table from src_engine into dst_engine.

    Steps per table:
        1. Reflect the source schema.
        2. Create the table in the destination if it doesn't exist.
        3. Truncate the destination table.
        4. Batch-insert all rows from source.
    """
    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    src_tables = src_meta.sorted_tables

    if not src_tables:
        db_label = bind_key or "main"
        print(f"  [{db_label}] No tables found in source – skipping.")
        return

    # Create tables in destination
    dst_meta = MetaData()
    dst_meta.reflect(bind=dst_engine)

    is_to_pg = 'postgresql' in str(dst_engine.url)

    for table in src_tables:
        # Create table in destination if needed
        if table.name not in dst_meta.tables:
            if is_to_pg:
                # Translate SQLite-specific types for PostgreSQL
                from sqlalchemy import Table as SA_Table, Column as SA_Column
                translated_cols = []
                for col in table.columns:
                    new_type = _translate_column_type(col.type)
                    translated_cols.append(SA_Column(
                        col.name, new_type,
                        primary_key=col.primary_key,
                        nullable=col.nullable,
                        autoincrement=col.autoincrement,
                    ))
                new_table = SA_Table(table.name, dst_meta, *translated_cols)
                dst_meta.create_all(bind=dst_engine, tables=[new_table])
            else:
                table.metadata.create_all(bind=dst_engine, tables=[table])
            print(f"  Created table '{table.name}' in destination.")

    # Re-reflect after creation
    dst_meta = MetaData()
    dst_meta.reflect(bind=dst_engine)

    # Copy data table by table
    for table in src_tables:
        table_name = table.name
        db_label = bind_key or "main"

        try:
            with src_engine.connect() as src_conn:
                rows = src_conn.execute(table.select()).fetchall()
                columns = [c.name for c in table.columns]

            if not rows:
                print(f"  [{db_label}] {table_name}: 0 rows (empty)")
                continue

            # Build list of dicts
            data = [dict(zip(columns, row)) for row in rows]

            # Sanitize data: convert any bytes to hex strings, None stays None
            for row_dict in data:
                for k, v in row_dict.items():
                    if isinstance(v, bytes):
                        row_dict[k] = v.hex()

            dst_table = dst_meta.tables.get(table_name)
            if dst_table is None:
                print(f"  [{db_label}] WARNING: table '{table_name}' missing in destination, skipping.")
                continue

            with dst_engine.begin() as dst_conn:
                # Truncate destination table
                # For PostgreSQL use TRUNCATE ... CASCADE, for SQLite use DELETE
                if 'postgresql' in str(dst_engine.url):
                    try:
                        dst_conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
                    except Exception:
                        dst_conn.execute(text(f'DELETE FROM "{table_name}"'))
                else:
                    dst_conn.execute(text(f'DELETE FROM "{table_name}"'))

                # Batch insert (chunks of 500)
                BATCH = 500
                for i in range(0, len(data), BATCH):
                    batch = data[i:i + BATCH]
                    dst_conn.execute(dst_table.insert(), batch)

            print(f"  [{db_label}] {table_name}: {len(data)} rows migrated")

        except Exception as e:
            print(f"  [{db_label}] ERROR migrating '{table_name}': {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _ensure_pg_tables(pg_cfg: dict):
    """
    Create all application tables in PostgreSQL using the Flask app models.
    This ensures tables exist even when the SQLite source is empty or missing.
    """
    try:
        # Import the app factory and create a temporary app context
        sys.path.insert(0, PROJECT_ROOT)
        from app import create_app, db as app_db
        temp_app = create_app(use_postgres=True)
        with temp_app.app_context():
            app_db.create_all()
            for bind_key in ('users', 'pages', 'misc'):
                try:
                    app_db.create_all(bind_key=bind_key)
                except Exception:
                    pass
        print("  [setup] Ensured all application tables exist in PostgreSQL.")
    except Exception as e:
        print(f"  [setup] Note: Could not pre-create tables from app models ({e}).")
        print("  [setup] Tables will be created from SQLite schema reflection instead.")


def migrate_sqlite_to_postgres(verbose: bool = True) -> dict:
    """
    Migrate all data from the local SQLite databases into PostgreSQL.

    Returns a summary dict: {"success": bool, "details": {...}}
    """
    pg_cfg = _load_pg_config()
    results = {}
    overall_ok = True

    if verbose:
        print("=" * 60)
        print("  SQLite  →  PostgreSQL  Migration")
        print("=" * 60)

    # Ensure all tables exist in PostgreSQL before copying data
    _ensure_pg_tables(pg_cfg)

    for bind_key, sqlite_file in SQLITE_DB_MAP.items():
        sqlite_path = os.path.join(INSTANCE_DIR, sqlite_file)
        label = bind_key or "main"

        if not os.path.exists(sqlite_path):
            if verbose:
                print(f"\n[{label}] SQLite file not found ({sqlite_file}) – skipping.")
            results[label] = "skipped – file not found"
            continue

        if verbose:
            print(f"\n[{label}] {sqlite_file}  →  {pg_cfg[{'users': 'database_users', 'pages': 'database_pages', 'misc': 'database_misc'}.get(bind_key, 'database')]}")

        try:
            src = create_engine(_sqlite_uri(sqlite_file))
            dst = create_engine(_pg_uri(pg_cfg, bind_key))
            _copy_tables(src, dst, bind_key, direction="sqlite-to-postgres")
            results[label] = "success"
        except Exception as e:
            results[label] = f"error: {e}"
            overall_ok = False
            if verbose:
                print(f"  [{label}] Migration FAILED: {e}")
        finally:
            try:
                src.dispose()
            except Exception:
                pass
            try:
                dst.dispose()
            except Exception:
                pass

    if verbose:
        print("\n" + "=" * 60)
        status = "COMPLETE" if overall_ok else "COMPLETED WITH ERRORS"
        print(f"  Migration {status}")
        print("=" * 60)

    return {"success": overall_ok, "details": results}


def migrate_postgres_to_sqlite(verbose: bool = True) -> dict:
    """
    Migrate all data from PostgreSQL back into local SQLite databases.

    Returns a summary dict: {"success": bool, "details": {...}}
    """
    pg_cfg = _load_pg_config()
    results = {}
    overall_ok = True

    if verbose:
        print("=" * 60)
        print("  PostgreSQL  →  SQLite  Migration")
        print("=" * 60)

    # Ensure instance dir exists
    os.makedirs(INSTANCE_DIR, exist_ok=True)

    for bind_key, sqlite_file in SQLITE_DB_MAP.items():
        label = bind_key or "main"
        pg_db_key = {
            'users': 'database_users',
            'pages': 'database_pages',
            'misc':  'database_misc',
        }.get(bind_key, 'database')

        if verbose:
            print(f"\n[{label}] {pg_cfg[pg_db_key]}  →  {sqlite_file}")

        try:
            src = create_engine(_pg_uri(pg_cfg, bind_key))
            dst = create_engine(_sqlite_uri(sqlite_file))

            # Enable WAL on the SQLite side for safety
            with dst.connect() as c:
                c.execute(text("PRAGMA journal_mode=WAL"))
                c.commit()

            _copy_tables(src, dst, bind_key, direction="postgres-to-sqlite")
            results[label] = "success"
        except Exception as e:
            results[label] = f"error: {e}"
            overall_ok = False
            if verbose:
                print(f"  [{label}] Migration FAILED: {e}")
        finally:
            try:
                src.dispose()
            except Exception:
                pass
            try:
                dst.dispose()
            except Exception:
                pass

    if verbose:
        print("\n" + "=" * 60)
        status = "COMPLETE" if overall_ok else "COMPLETED WITH ERRORS"
        print(f"  Migration {status}")
        print("=" * 60)

    return {"success": overall_ok, "details": results}


def get_migration_status() -> dict:
    """
    Return a quick comparison of row counts between SQLite and PostgreSQL
    for each database / table.  Useful for admin dashboards.
    """
    pg_cfg = _load_pg_config()
    report = {}

    for bind_key, sqlite_file in SQLITE_DB_MAP.items():
        label = bind_key or "main"
        sqlite_path = os.path.join(INSTANCE_DIR, sqlite_file)
        entry: dict = {"sqlite_exists": os.path.exists(sqlite_path), "tables": {}}

        # SQLite counts
        sqlite_counts = {}
        if entry["sqlite_exists"]:
            try:
                eng = create_engine(_sqlite_uri(sqlite_file))
                meta = MetaData()
                meta.reflect(bind=eng)
                with eng.connect() as conn:
                    for t in meta.sorted_tables:
                        count = conn.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar()
                        sqlite_counts[t.name] = count
                eng.dispose()
            except Exception as e:
                entry["sqlite_error"] = str(e)

        # Postgres counts
        pg_counts = {}
        try:
            eng = create_engine(_pg_uri(pg_cfg, bind_key))
            meta = MetaData()
            meta.reflect(bind=eng)
            with eng.connect() as conn:
                for t in meta.sorted_tables:
                    count = conn.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar()
                    pg_counts[t.name] = count
            eng.dispose()
        except Exception as e:
            entry["pg_error"] = str(e)

        # Merge
        all_tables = sorted(set(list(sqlite_counts.keys()) + list(pg_counts.keys())))
        for tn in all_tables:
            entry["tables"][tn] = {
                "sqlite_rows": sqlite_counts.get(tn, "n/a"),
                "postgres_rows": pg_counts.get(tn, "n/a"),
            }

        report[label] = entry

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Obsidian Scout – SQLite ↔ PostgreSQL Migration")
    parser.add_argument(
        "--direction", "-d",
        choices=["sqlite-to-postgres", "postgres-to-sqlite", "status"],
        default="status",
        help="Migration direction or 'status' to compare row counts. (default: status)",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress verbose output")

    args = parser.parse_args()

    if args.direction == "sqlite-to-postgres":
        result = migrate_sqlite_to_postgres(verbose=not args.quiet)
    elif args.direction == "postgres-to-sqlite":
        result = migrate_postgres_to_sqlite(verbose=not args.quiet)
    else:
        result = get_migration_status()
        print(json.dumps(result, indent=2, default=str))
        return

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
