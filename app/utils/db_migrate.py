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
import traceback
from datetime import datetime, timezone

try:
    from sqlalchemy import create_engine, inspect, text, MetaData, Column
    from sqlalchemy.exc import OperationalError, ProgrammingError, IntegrityError
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
    # Check instance/ first (per-install, writable), then config/ as fallback
    # This mirrors the priority order used by postgres_manager._load_config()
    config_candidates = [
        os.path.join(PROJECT_ROOT, 'instance', 'postgres_config.json'),
        os.path.join(PROJECT_ROOT, 'config', 'postgres_config.json'),
    ]
    for cfg_path in config_candidates:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    file_cfg = json.load(f)
                defaults.update({k: v for k, v in file_cfg.items() if v is not None})
                break  # stop at first found (instance preferred)
            except Exception as e:
                print(f"  [config] Warning: could not read {cfg_path}: {e}")
                continue
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


# ---------------------------------------------------------------------------
# Type coercion helpers for SQLite → PostgreSQL
# ---------------------------------------------------------------------------
# SQLite is dynamically typed: an INTEGER column can actually hold any string.
# PostgreSQL rejects these.  We introspect the *destination* table's column
# types and coerce each value before INSERT.

def _coerce_value(value, col_type, col_name: str):
    """
    Coerce *value* to match the destination column's *col_type*.
    Returns (coerced_value, warning_or_None).
    """
    if value is None:
        return None, None

    type_name = type(col_type).__name__.upper()

    # Integer / BigInteger / SmallInteger
    if 'INT' in type_name:
        if isinstance(value, int):
            return value, None
        if isinstance(value, float):
            return int(value), None
        if isinstance(value, str):
            # Try plain int conversion first
            try:
                return int(value), None
            except (ValueError, TypeError):
                pass
            # Try stripping whitespace / leading zeros
            stripped = value.strip()
            if stripped.lstrip('-').isdigit():
                return int(stripped), None
            # Unconvertible string in an integer column → NULL it out
            return None, f"Cannot convert '{value}' to integer for column '{col_name}' – set to NULL"
        if isinstance(value, bool):
            return int(value), None
        # Fallback: can't convert
        return None, f"Unexpected type {type(value).__name__} for integer column '{col_name}' – set to NULL"

    # Float / Real / Double
    if type_name in ('FLOAT', 'REAL', 'DOUBLE', 'DOUBLE_PRECISION', 'NUMERIC'):
        if isinstance(value, (int, float)):
            return float(value), None
        if isinstance(value, str):
            try:
                return float(value), None
            except (ValueError, TypeError):
                return None, f"Cannot convert '{value}' to float for column '{col_name}' – set to NULL"

    # Boolean
    if 'BOOL' in type_name:
        if isinstance(value, bool):
            return value, None
        if isinstance(value, int):
            return bool(value), None
        if isinstance(value, str):
            if value.lower() in ('true', '1', 'yes', 't'):
                return True, None
            if value.lower() in ('false', '0', 'no', 'f', ''):
                return False, None
            return None, f"Cannot convert '{value}' to boolean for column '{col_name}' – set to NULL"

    # DateTime / Timestamp
    if 'DATE' in type_name or 'TIME' in type_name:
        if isinstance(value, (datetime,)):
            return value, None
        if isinstance(value, str):
            # Try common ISO formats
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f',
                        '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%d'):
                try:
                    return datetime.strptime(value, fmt), None
                except ValueError:
                    continue
            # Let the DB try to parse it
            return value, None

    # Bytes → hex string (for LargeBinary going to PG)
    if isinstance(value, bytes):
        return value.hex(), None

    # Everything else: pass through unchanged
    return value, None


def _coerce_row(row_dict: dict, dst_columns: dict, table_name: str) -> tuple:
    """
    Coerce every value in *row_dict* to match destination column types.
    Also handles special cross-column logic (e.g. match_number → display_match_number).
    Returns (coerced_dict, list_of_warnings).
    """
    warnings = []
    coerced = {}

    # --- Special handling: match_number with dash-style playoff values ---
    # Values like '1-1', '10-1' are playoff match identifiers.  The model
    # stores the numeric part in match_number (Integer) and the original
    # human-friendly string in display_match_number (String).
    if 'match_number' in row_dict and 'match_number' in dst_columns:
        mn_val = row_dict.get('match_number')
        if isinstance(mn_val, str) and '-' in mn_val:
            # Save original to display_match_number if that column exists
            # and isn't already populated
            if 'display_match_number' in dst_columns:
                existing_display = row_dict.get('display_match_number')
                if not existing_display:
                    row_dict['display_match_number'] = mn_val
            # Extract leading numeric portion for match_number
            parts = mn_val.split('-')
            try:
                row_dict['match_number'] = int(parts[0])
            except (ValueError, TypeError):
                row_dict['match_number'] = None
                warnings.append(f"Cannot extract number from match_number '{mn_val}' – set to NULL")

    for col_name, value in row_dict.items():
        if col_name in dst_columns:
            coerced_val, warn = _coerce_value(value, dst_columns[col_name].type, col_name)
            coerced[col_name] = coerced_val
            if warn:
                warnings.append(warn)
        else:
            coerced[col_name] = value
    return coerced, warnings


def _copy_tables(src_engine, dst_engine, bind_key: str | None, direction: str):
    """
    Copy every table from src_engine into dst_engine.

    Steps per table:
        1. Reflect the source schema.
        2. Create the table in the destination if it doesn't exist.
        3. Truncate the destination table (with FKs deferred).
        4. Insert rows one-by-one with type coercion and per-row error handling.
    """
    src_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    src_tables = src_meta.sorted_tables   # topological order respects FK dependencies

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

    # Re-reflect after creation so we have accurate destination column types
    dst_meta = MetaData()
    dst_meta.reflect(bind=dst_engine)

    # Build a column-type lookup per destination table for coercion
    dst_col_map: dict[str, dict] = {}
    for tname, tobj in dst_meta.tables.items():
        dst_col_map[tname] = {c.name: c for c in tobj.columns}

    # If migrating to PostgreSQL, temporarily disable FK checks for the
    # TRUNCATE + INSERT pass, then re-enable so the DB enforces constraints
    # going forward.

    # ----- Truncate all destination tables first (reverse order for FKs) -----
    if is_to_pg:
        with dst_engine.begin() as conn:
            # Disable FK triggers so TRUNCATE doesn't cascade-fail
            conn.execute(text("SET session_replication_role = 'replica'"))
            for table in reversed(src_tables):
                tname = table.name
                if tname in dst_meta.tables:
                    try:
                        conn.execute(text(f'TRUNCATE TABLE "{tname}" CASCADE'))
                    except Exception:
                        try:
                            conn.execute(text(f'DELETE FROM "{tname}"'))
                        except Exception:
                            pass
            conn.execute(text("SET session_replication_role = 'origin'"))
    else:
        # SQLite: delete in reverse FK order
        with dst_engine.begin() as conn:
            for table in reversed(src_tables):
                tname = table.name
                if tname in dst_meta.tables:
                    try:
                        conn.execute(text(f'DELETE FROM "{tname}"'))
                    except Exception:
                        pass

    # ----- Copy data table-by-table in FK-dependency order -----
    total_migrated = 0
    total_skipped = 0
    total_warnings = 0

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

            dst_table = dst_meta.tables.get(table_name)
            if dst_table is None:
                print(f"  [{db_label}] WARNING: table '{table_name}' missing in destination, skipping.")
                continue

            # The destination table may have columns the source doesn't
            # (e.g. display_match_number).  Build the dst column list
            # so the coercion layer can populate them.
            dst_col_names = set(c.name for c in dst_table.columns)
            col_types = dst_col_map.get(table_name, {})
            migrated = 0
            skipped = 0
            row_warnings = 0
            # Track unique coercion warnings to avoid spam
            seen_warnings: dict[str, int] = {}  # message -> count

            # Insert rows with per-row error handling.
            # Each row is wrapped in a SAVEPOINT so a single failure
            # does NOT abort the entire PostgreSQL transaction.
            with dst_engine.begin() as dst_conn:
                # For PostgreSQL, temporarily disable FK constraints during insert
                if is_to_pg:
                    dst_conn.execute(text("SET session_replication_role = 'replica'"))

                for raw_row in rows:
                    row_dict = dict(zip(columns, raw_row))

                    # Type coercion
                    if is_to_pg and col_types:
                        coerced, warns = _coerce_row(row_dict, col_types, table_name)
                        for w in warns:
                            seen_warnings[w] = seen_warnings.get(w, 0) + 1
                            row_warnings += 1
                        row_dict = coerced
                    else:
                        # Still sanitize bytes
                        for k, v in row_dict.items():
                            if isinstance(v, bytes):
                                row_dict[k] = v.hex()

                    # Only include columns that exist in the destination table
                    insert_dict = {k: v for k, v in row_dict.items() if k in dst_col_names}

                    try:
                        # Use a SAVEPOINT so one bad row doesn't abort the
                        # whole PG transaction (InFailedSqlTransaction)
                        nested = dst_conn.begin_nested()
                        try:
                            dst_conn.execute(dst_table.insert(), insert_dict)
                            nested.commit()
                            migrated += 1
                        except IntegrityError as ie:
                            nested.rollback()
                            skipped += 1
                            if skipped <= 5:
                                print(f"  [{db_label}] {table_name}: SKIPPED row (integrity): {ie.orig}")
                            elif skipped == 6:
                                print(f"  [{db_label}] {table_name}: (further skip messages suppressed)")
                        except Exception as ex:
                            nested.rollback()
                            skipped += 1
                            if skipped <= 5:
                                print(f"  [{db_label}] {table_name}: SKIPPED row (error): {ex}")
                            elif skipped == 6:
                                print(f"  [{db_label}] {table_name}: (further skip messages suppressed)")
                    except Exception as sp_err:
                        # SAVEPOINT creation itself failed – skip row
                        skipped += 1
                        if skipped <= 3:
                            print(f"  [{db_label}] {table_name}: SAVEPOINT error: {sp_err}")

                # Re-enable FK constraints
                if is_to_pg:
                    dst_conn.execute(text("SET session_replication_role = 'origin'"))

            # Print deduplicated coercion warnings (max 5 unique messages)
            if seen_warnings:
                shown = 0
                for msg, count in seen_warnings.items():
                    if shown >= 5:
                        remaining = len(seen_warnings) - shown
                        print(f"  [{db_label}] {table_name}: ... and {remaining} more coercion warning type(s)")
                        break
                    suffix_w = f" (x{count})" if count > 1 else ""
                    print(f"  [{db_label}] {table_name}: {msg}{suffix_w}")
                    shown += 1

            suffix = ""
            if skipped:
                suffix += f", {skipped} skipped"
            if row_warnings:
                suffix += f", {row_warnings} coerced"
            print(f"  [{db_label}] {table_name}: {migrated} rows migrated{suffix}")

            total_migrated += migrated
            total_skipped += skipped
            total_warnings += row_warnings

        except Exception as e:
            print(f"  [{db_label}] ERROR migrating '{table_name}': {e}")
            traceback.print_exc()

    db_label = bind_key or "main"
    print(f"  [{db_label}] Totals: {total_migrated} migrated, {total_skipped} skipped, {total_warnings} coerced")


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

    # Reset PostgreSQL sequences so auto-increment picks up after
    # the highest migrated ID, not the stale default of 1.
    if overall_ok or any(v == "success" for v in results.values()):
        try:
            _reset_pg_sequences(pg_cfg)
        except Exception as e:
            print(f"  [sequences] Warning: could not reset sequences: {e}")

    return {"success": overall_ok, "details": results}


def _reset_pg_sequences(pg_cfg: dict):
    """
    After migrating data from SQLite, PostgreSQL serial/identity sequences
    still point at 1 (or wherever they were).  Reset every sequence to
    MAX(pk_column) + 1 so the next INSERT gets a correct auto-ID.
    """
    db_keys = [None, 'users', 'pages', 'misc']
    total_reset = 0
    for bind_key in db_keys:
        label = bind_key or 'main'
        try:
            engine = create_engine(_pg_uri(pg_cfg, bind_key))
            with engine.begin() as conn:
                # Find all sequences owned by columns (serial / GENERATED)
                rows = conn.execute(text("""
                    SELECT schemaname, sequencename
                    FROM pg_sequences
                    WHERE schemaname = 'public'
                """)).fetchall()
                for schema, seq_name in rows:
                    # Try to find the owning table + column
                    try:
                        info = conn.execute(text("""
                            SELECT d.refobjid::regclass AS table_name,
                                   a.attname AS column_name
                            FROM pg_depend d
                            JOIN pg_attribute a ON a.attrelid = d.refobjid
                                                AND a.attnum = d.refobjsubid
                            WHERE d.objid = :seq_oid::regclass
                              AND d.deptype = 'a'
                            LIMIT 1
                        """), {"seq_oid": f"public.{seq_name}"}).fetchone()
                    except Exception:
                        continue
                    if info:
                        tbl, col = str(info[0]), str(info[1])
                        try:
                            max_val = conn.execute(
                                text(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{tbl}"')
                            ).scalar()
                            conn.execute(text(
                                f"SELECT setval('public.\"{seq_name}\"', :val, true)"
                            ), {"val": max(max_val, 1)})
                            total_reset += 1
                        except Exception:
                            pass
            engine.dispose()
        except Exception as e:
            print(f"  [sequences] Warning: error resetting sequences for [{label}]: {e}")
    if total_reset:
        print(f"  [sequences] Reset {total_reset} PostgreSQL sequences to current max IDs.")


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
