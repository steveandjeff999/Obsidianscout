#!/usr/bin/env python3
"""
PostgreSQL Automated Manager for Obsidian Scout.

Handles:
- Auto-detecting PostgreSQL installation on Windows/Linux/macOS
- Starting/stopping the PostgreSQL server
- Creating the application databases if they don't exist
- Building connection URIs for SQLAlchemy
- Health checks

Usage:
    from app.utils.postgres_manager import PostgresManager
    pg = PostgresManager()
    pg.ensure_running()   # auto-start if not already running
    uri = pg.get_uri()    # main database URI
"""

import os
import sys
import time
import json
import shutil
import subprocess
import platform

# ---------------------------------------------------------------------------
# Default connection parameters – override via environment variables or
# config/postgres_config.json
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "host": "localhost",
    "port": 5432,
    "user": "obsidian_scout",
    "password": "obsidian_scout_pass",
    "superuser_password": "",
    "database": "obsidian_scout",
    "database_users": "obsidian_scout_users",
    "database_pages": "obsidian_scout_pages",
    "database_misc": "obsidian_scout_misc",
}

# Prefer instance/postgres_config.json so per-install settings are writable
INSTANCE_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'instance', 'postgres_config.json'
)
FALLBACK_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config', 'postgres_config.json'
)
CONFIG_FILE_CANDIDATES = [INSTANCE_CONFIG, FALLBACK_CONFIG]


def _load_config() -> dict:
    """Load PostgreSQL config from file, env vars, or defaults."""
    cfg = dict(_DEFAULTS)

    # 1. Override from config file(s) - prefer instance/ then config/
    try:
        for candidate in CONFIG_FILE_CANDIDATES:
            if os.path.exists(candidate):
                try:
                    with open(candidate, 'r', encoding='utf-8') as f:
                        file_cfg = json.load(f)
                    cfg.update({k: v for k, v in file_cfg.items() if v is not None})
                    # stop at first found (instance preferred)
                    break
                except Exception as _e:
                    print(f"[PostgresManager] Warning: could not read {candidate}: {_e}", flush=True)
                    continue
    except Exception as e:
        print(f"[PostgresManager] Warning: error while reading postgres config: {e}", flush=True)

    # 2. Override from environment variables
    env_map = {
        "POSTGRES_HOST": "host",
        "POSTGRES_PORT": "port",
        "POSTGRES_USER": "user",
        "POSTGRES_PASSWORD": "password",
        "POSTGRES_DB": "database",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            cfg[cfg_key] = int(val) if cfg_key == "port" else val

    return cfg


def save_default_config():
    """Write a default postgres_config.json if one doesn't exist."""
    # Create the instance-level config by default so it's writable per-install
    target = INSTANCE_CONFIG
    if os.path.exists(target):
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(_DEFAULTS, f, indent=2)
        print(f"[PostgresManager] Created default config at {target}", flush=True)
    except Exception as e:
        print(f"[PostgresManager] Could not write default config: {e}", flush=True)


class PostgresManager:
    """Fully automated PostgreSQL lifecycle manager."""

    def __init__(self):
        self.cfg = _load_config()
        self._validate_config()
        print("[PostgresManager] Scanning for PostgreSQL installation...", flush=True)
        self._pg_bin = self._find_pg_bin()
        if self._pg_bin:
            print(f"[PostgresManager] Found PostgreSQL binaries at: {self._pg_bin}", flush=True)
        else:
            print("[PostgresManager] PostgreSQL binaries not found on PATH or standard install locations.", flush=True)
            print("[PostgresManager] Will attempt direct connection via psycopg2 driver.", flush=True)

    def _validate_config(self):
        """Check config for obvious problems and warn early."""
        su_pass = self.cfg.get("superuser_password", "") or ""
        if not su_pass or su_pass == "your_postgres_superuser_password_here":
            print("[PostgresManager] WARNING: superuser_password is not set in config/postgres_config.json", flush=True)
            print("   You must set this to the password you chose when installing PostgreSQL.", flush=True)
            print("   Without it, database provisioning will fail.", flush=True)
            # Clear it so we don't try the placeholder string as a real password
            self.cfg["superuser_password"] = ""

    # ------------------------------------------------------------------
    # Path discovery
    # ------------------------------------------------------------------
    def _find_pg_bin(self) -> str | None:
        """Locate the PostgreSQL bin directory."""
        # Check PATH first
        if shutil.which("pg_isready"):
            return os.path.dirname(shutil.which("pg_isready"))

        system = platform.system()
        search_dirs: list[str] = []

        if system == "Windows":
            # Common Windows install locations
            for drive in ("C:", "D:"):
                pg_base = os.path.join(drive, os.sep, "Program Files", "PostgreSQL")
                if os.path.isdir(pg_base):
                    for ver in sorted(os.listdir(pg_base), reverse=True):
                        candidate = os.path.join(pg_base, ver, "bin")
                        if os.path.isfile(os.path.join(candidate, "pg_isready.exe")):
                            search_dirs.append(candidate)
            # Also check EnterpriseDB default
            edb = os.path.join("C:", os.sep, "edb", "as17", "bin")
            if os.path.isdir(edb):
                search_dirs.append(edb)
        elif system == "Darwin":
            # Homebrew
            for p in ("/opt/homebrew/bin", "/usr/local/bin"):
                if os.path.isfile(os.path.join(p, "pg_isready")):
                    search_dirs.append(p)
            # Postgres.app
            pg_app = "/Applications/Postgres.app/Contents/Versions"
            if os.path.isdir(pg_app):
                for ver in sorted(os.listdir(pg_app), reverse=True):
                    candidate = os.path.join(pg_app, ver, "bin")
                    if os.path.isfile(os.path.join(candidate, "pg_isready")):
                        search_dirs.append(candidate)
        else:
            # Linux – typical package manager paths
            for p in ("/usr/bin", "/usr/lib/postgresql"):
                if os.path.isdir(p):
                    if os.path.isfile(os.path.join(p, "pg_isready")):
                        search_dirs.append(p)
                    # /usr/lib/postgresql/<ver>/bin
                    for ver in sorted(os.listdir(p), reverse=True) if p.endswith("postgresql") else []:
                        candidate = os.path.join(p, ver, "bin")
                        if os.path.isfile(os.path.join(candidate, "pg_isready")):
                            search_dirs.append(candidate)

        return search_dirs[0] if search_dirs else None

    def _bin(self, name: str) -> str:
        """Return full path to a PG binary, falling back to bare name."""
        if self._pg_bin:
            ext = ".exe" if platform.system() == "Windows" else ""
            full = os.path.join(self._pg_bin, name + ext)
            if os.path.isfile(full):
                return full
        return name  # hope it's on PATH

    # ------------------------------------------------------------------
    # Installation detection
    # ------------------------------------------------------------------
    def is_installed(self) -> bool:
        """Check whether PostgreSQL is installed (binaries found or psycopg2 can connect)."""
        if self._pg_bin:
            return True
        # Even without local binaries we can connect if PG is on a remote host
        # or running as a managed service – try psycopg2
        return self._can_connect_psycopg2()

    def _can_connect_psycopg2(self) -> bool:
        """Try a direct TCP connection to PostgreSQL via psycopg2."""
        # Try as app user first
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=self.cfg["host"],
                port=self.cfg["port"],
                user=self.cfg["user"],
                password=self.cfg["password"],
                dbname="postgres",
                connect_timeout=3,
            )
            conn.close()
            return True
        except Exception:
            pass
        # Try with postgres superuser + configured superuser_password
        su_pass = self.cfg.get("superuser_password", "") or ""
        if su_pass:
            try:
                import psycopg2
                conn = psycopg2.connect(
                    host=self.cfg["host"],
                    port=self.cfg["port"],
                    user="postgres",
                    password=su_pass,
                    dbname="postgres",
                    connect_timeout=3,
                )
                conn.close()
                return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        """Check if PostgreSQL is accepting connections."""
        print("[PostgresManager]   Checking if PostgreSQL is accepting connections...", flush=True)
        # Method 1: pg_isready (fast, preferred)
        if self._pg_bin:
            try:
                result = subprocess.run(
                    [self._bin("pg_isready"),
                     "-h", self.cfg["host"],
                     "-p", str(self.cfg["port"])],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    print("[PostgresManager]   -> pg_isready: accepting connections.", flush=True)
                    return True
                else:
                    print(f"[PostgresManager]   -> pg_isready: not ready (rc={result.returncode}).", flush=True)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[PostgresManager]   -> pg_isready error: {e}", flush=True)

        # Method 2: direct psycopg2 connection (works without PG binaries)
        print("[PostgresManager]   Trying direct psycopg2 connection...", flush=True)
        if self._can_connect_psycopg2():
            print("[PostgresManager]   -> Connected via psycopg2.", flush=True)
            return True

        print("[PostgresManager]   -> PostgreSQL is not reachable.", flush=True)
        return False

    def start_server(self) -> bool:
        """Attempt to start PostgreSQL if it's not already running."""
        if self.is_running():
            print("[PostgresManager] PostgreSQL is already running.")
            return True

        system = platform.system()
        print("[PostgresManager] Starting PostgreSQL server...")

        try:
            if system == "Windows":
                # Try Windows service – check highest version first
                for svc in ("postgresql-x64-18", "postgresql-x64-17",
                             "postgresql-x64-16", "postgresql-x64-15",
                             "postgresql-x64-14", "postgresql",
                             "postgresql-18", "postgresql-17", "postgresql-16"):
                    try:
                        subprocess.run(
                            ["net", "start", svc],
                            capture_output=True, text=True, timeout=30,
                        )
                        if self.is_running():
                            print(f"[PostgresManager] PostgreSQL started via service '{svc}'.")
                            return True
                    except Exception:
                        continue

                # Fallback: pg_ctl with auto-detected data directory
                data_dir = self._find_data_dir()
                if data_dir:
                    subprocess.Popen(
                        [self._bin("pg_ctl"), "start", "-D", data_dir, "-w"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    time.sleep(3)
                    if self.is_running():
                        print(f"[PostgresManager] PostgreSQL started via pg_ctl (data={data_dir}).")
                        return True

            elif system == "Darwin":
                # macOS – try brew services, then Postgres.app, then pg_ctl
                for cmd in (
                    ["brew", "services", "start", "postgresql"],
                    ["brew", "services", "start", "postgresql@17"],
                    ["brew", "services", "start", "postgresql@16"],
                ):
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=15)
                        time.sleep(2)
                        if self.is_running():
                            print("[PostgresManager] PostgreSQL started via Homebrew.")
                            return True
                    except Exception:
                        continue

            else:
                # Linux – systemctl
                for svc in ("postgresql", "postgresql-17", "postgresql-16"):
                    try:
                        subprocess.run(
                            ["sudo", "systemctl", "start", svc],
                            capture_output=True, timeout=15,
                        )
                        time.sleep(2)
                        if self.is_running():
                            print(f"[PostgresManager] PostgreSQL started via systemctl ({svc}).")
                            return True
                    except Exception:
                        continue

        except Exception as e:
            print(f"[PostgresManager] Error starting PostgreSQL: {e}")

        if self.is_running():
            return True

        print("[PostgresManager] ERROR: Could not start PostgreSQL automatically.")
        print("")
        print("   PostgreSQL does not appear to be installed or is not reachable.")
        print("   To use PostgreSQL mode, do ONE of the following:")
        print("")
        print("   Option A – Install locally:")
        print("     1. Download from https://www.postgresql.org/download/")
        print("     2. Run the installer (remember the password you set for 'postgres' superuser)")
        print("     3. Restart this application")
        print("")
        print("   Option B – Use a remote/managed PostgreSQL:")
        print("     1. Edit config/postgres_config.json with the remote host, port, user, password")
        print("     2. Restart this application")
        print("")
        print("   Option C – Keep using SQLite (no action needed, set USE_POSTGRES = False in run.py)")
        print("")
        return False

    def _find_data_dir(self) -> str | None:
        """Try to find the PostgreSQL data directory on Windows."""
        for drive in ("C:", "D:"):
            pg_base = os.path.join(drive, os.sep, "Program Files", "PostgreSQL")
            if os.path.isdir(pg_base):
                for ver in sorted(os.listdir(pg_base), reverse=True):
                    candidate = os.path.join(pg_base, ver, "data")
                    if os.path.isdir(candidate):
                        return candidate
        return None

    def stop_server(self):
        """Stop PostgreSQL (best-effort)."""
        system = platform.system()
        if system == "Windows":
            for svc in ("postgresql-x64-17", "postgresql-x64-16",
                         "postgresql-x64-15", "postgresql"):
                try:
                    subprocess.run(["net", "stop", svc],
                                   capture_output=True, timeout=30)
                except Exception:
                    continue
        elif system == "Darwin":
            subprocess.run(["brew", "services", "stop", "postgresql"],
                           capture_output=True, timeout=15)
        else:
            subprocess.run(["sudo", "systemctl", "stop", "postgresql"],
                           capture_output=True, timeout=15)

    # ------------------------------------------------------------------
    # Database / role provisioning
    # ------------------------------------------------------------------
    def _run_psql(self, sql: str, dbname: str = "postgres") -> tuple[bool, str]:
        """Execute a SQL statement via psql and return (success, output)."""
        env = os.environ.copy()
        env["PGPASSWORD"] = self.cfg["password"]
        try:
            r = subprocess.run(
                [self._bin("psql"),
                 "-h", self.cfg["host"],
                 "-p", str(self.cfg["port"]),
                 "-U", self.cfg["user"],
                 "-d", dbname,
                 "-w",
                 "-c", sql],
                capture_output=True, text=True, timeout=15, env=env,
            )
            return r.returncode == 0, r.stdout + r.stderr
        except Exception as e:
            return False, str(e)

    def _run_psql_as_superuser(self, sql: str, dbname: str = "postgres") -> tuple[bool, str]:
        """Execute SQL via psql using the default 'postgres' superuser."""
        env = os.environ.copy()
        # Set PGPASSWORD from config so psql never prompts interactively
        su_pass = self.cfg.get("superuser_password", "") or ""
        if su_pass:
            env["PGPASSWORD"] = su_pass
        try:
            r = subprocess.run(
                [self._bin("psql"),
                 "-h", self.cfg["host"],
                 "-p", str(self.cfg["port"]),
                 "-U", "postgres",
                 "-d", dbname,
                 "-w",
                 "-c", sql],
                capture_output=True, text=True, timeout=15, env=env,
            )
            return r.returncode == 0, r.stdout + r.stderr
        except Exception as e:
            return False, str(e)

    def ensure_role_and_databases(self):
        """Create the application role and databases if they don't exist."""
        user = self.cfg["user"]
        password = self.cfg["password"]
        databases = [
            self.cfg["database"],
            self.cfg["database_users"],
            self.cfg["database_pages"],
            self.cfg["database_misc"],
        ]

        print(f"[PostgresManager] Ensuring role '{user}' and databases exist...", flush=True)

        # Always prefer psycopg2 for provisioning (no interactive password prompts)
        # Only fall back to psql CLI if psycopg2 fails
        try:
            print("[PostgresManager]   Provisioning via psycopg2...", flush=True)
            self._provision_via_psycopg2(user, password, databases)
            return
        except Exception as e:
            print(f"[PostgresManager]   psycopg2 provisioning failed ({e}), trying psql CLI...", flush=True)
        if self._pg_bin:
            self._provision_via_psql(user, password, databases)
        else:
            print("[PostgresManager] ERROR: Cannot provision databases – no psql CLI and psycopg2 failed.", flush=True)

    def _provision_via_psql(self, user, password, databases):
        """Provision role and databases using psql CLI."""
        # Create role if missing
        create_role_sql = (
            f"DO $$ BEGIN "
            f"  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{user}') THEN "
            f"    CREATE ROLE \"{user}\" WITH LOGIN PASSWORD '{password}' CREATEDB; "
            f"  END IF; "
            f"END $$;"
        )
        ok, out = self._run_psql_as_superuser(create_role_sql)
        if not ok:
            print(f"[PostgresManager] Warning creating role: {out.strip()}")
        else:
            print(f"[PostgresManager] Role '{user}' ready.")

        # Create each database if missing
        for db_name in databases:
            check_sql = f"SELECT 1 FROM pg_database WHERE datname = '{db_name}';"
            ok, out = self._run_psql_as_superuser(check_sql)
            if db_name not in out or "0 rows" in out:
                create_sql = f'CREATE DATABASE "{db_name}" OWNER "{user}";'
                ok2, out2 = self._run_psql_as_superuser(create_sql)
                if ok2 or "already exists" in out2:
                    print(f"[PostgresManager] Database '{db_name}' ready.")
                else:
                    print(f"[PostgresManager] Warning creating DB '{db_name}': {out2.strip()}")
            else:
                print(f"[PostgresManager] Database '{db_name}' already exists.")

        # Grant privileges (database-level AND schema/table-level for PG 15+)
        for db_name in databases:
            grant_sql = f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{user}";'
            self._run_psql_as_superuser(grant_sql)
        # Schema & table grants must be run while connected to each database
        for db_name in databases:
            schema_grants = (
                f'GRANT ALL ON SCHEMA public TO "{user}"; '
                f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{user}"; '
                f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{user}"; '
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{user}"; '
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{user}";'
            )
            self._run_psql_as_superuser(schema_grants, dbname=db_name)

    def _provision_via_psycopg2(self, user, password, databases):
        """Provision role and databases using psycopg2 (no CLI tools needed)."""
        try:
            import psycopg2
            from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        except ImportError:
            print("[PostgresManager] psycopg2 not installed – cannot provision databases.")
            print("   Run: pip install psycopg2-binary")
            return

        # Connect as postgres superuser
        su_user = "postgres"
        # Password priority: config file > env var > app password > empty
        su_pass_cfg = self.cfg.get("superuser_password", "") or ""
        su_pass_env = os.environ.get("POSTGRES_SUPERUSER_PASSWORD", "")
        candidate_passwords = []
        if su_pass_cfg:
            candidate_passwords.append(su_pass_cfg)
        if su_pass_env:
            candidate_passwords.append(su_pass_env)
        candidate_passwords.append(password)
        # Don't try empty password — it just wastes time on password-required servers

        conn = None
        for i, attempt_pass in enumerate(candidate_passwords):
            masked = attempt_pass[:2] + "***" if len(attempt_pass) > 2 else "***"
            print(f"[PostgresManager]   Trying superuser connection (attempt {i+1}/{len(candidate_passwords)}, pw={masked})...", flush=True)
            try:
                conn = psycopg2.connect(
                    host=self.cfg["host"],
                    port=self.cfg["port"],
                    user=su_user,
                    password=attempt_pass,
                    dbname="postgres",
                    connect_timeout=3,
                )
                print(f"[PostgresManager]   Connected as '{su_user}' superuser.", flush=True)
                break
            except Exception as ex:
                print(f"[PostgresManager]   -> Failed: {ex}", flush=True)
                continue

        if conn is None:
            print("[PostgresManager] Could not connect as 'postgres' superuser.", flush=True)
            print('   Set "superuser_password" in config/postgres_config.json', flush=True)
            print("   (this is the password you chose when installing PostgreSQL)", flush=True)
            # Try connecting as the app user instead (they may exist already)
            print(f"[PostgresManager]   Trying as app user '{user}'...", flush=True)
            try:
                conn = psycopg2.connect(
                    host=self.cfg["host"],
                    port=self.cfg["port"],
                    user=user,
                    password=password,
                    dbname="postgres",
                    connect_timeout=3,
                )
                print(f"[PostgresManager]   Connected as app user '{user}'.", flush=True)
            except Exception as e2:
                print(f"[PostgresManager]   Also could not connect as '{user}': {e2}", flush=True)
                return

        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Create role if missing
        try:
            cur.execute("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s", (user,))
            if not cur.fetchone():
                cur.execute(f'CREATE ROLE "{user}" WITH LOGIN PASSWORD %s CREATEDB', (password,))
                print(f"[PostgresManager] Created role '{user}'.")
            else:
                print(f"[PostgresManager] Role '{user}' already exists.")
        except Exception as e:
            print(f"[PostgresManager] Warning creating role: {e}")

        # Create databases
        for db_name in databases:
            try:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                if not cur.fetchone():
                    cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{user}"')
                    print(f"[PostgresManager] Created database '{db_name}'.")
                else:
                    print(f"[PostgresManager] Database '{db_name}' already exists.")
            except Exception as e:
                if "already exists" in str(e):
                    print(f"[PostgresManager] Database '{db_name}' already exists.")
                else:
                    print(f"[PostgresManager] Warning creating DB '{db_name}': {e}")

        # Grant privileges (database-level AND schema/table-level for PG 15+)
        for db_name in databases:
            try:
                cur.execute(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{user}"')
            except Exception:
                pass

        # Schema & table grants must be run while connected to each target DB
        cur.close()
        conn.close()
        for db_name in databases:
            try:
                db_conn = psycopg2.connect(
                    host=self.cfg["host"],
                    port=self.cfg["port"],
                    user=su_user if conn else user,
                    password=candidate_passwords[0] if candidate_passwords else password,
                    dbname=db_name,
                    connect_timeout=3,
                )
                db_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                db_cur = db_conn.cursor()
                try:
                    db_cur.execute(f'GRANT ALL ON SCHEMA public TO "{user}"')
                    db_cur.execute(f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{user}"')
                    db_cur.execute(f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{user}"')
                    db_cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{user}"')
                    db_cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{user}"')
                except Exception:
                    pass
                db_cur.close()
                db_conn.close()
            except Exception:
                pass
        print("[PostgresManager] Database provisioning complete.")

    # ------------------------------------------------------------------
    # URI builders
    # ------------------------------------------------------------------
    def _make_uri(self, dbname: str) -> str:
        c = self.cfg
        return f"postgresql://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{dbname}"

    def get_uri(self) -> str:
        return self._make_uri(self.cfg["database"])

    def get_binds(self) -> dict:
        return {
            "users": self._make_uri(self.cfg["database_users"]),
            "pages": self._make_uri(self.cfg["database_pages"]),
            "misc":  self._make_uri(self.cfg["database_misc"]),
        }

    def get_engine_options(self) -> dict:
        """Return SQLAlchemy engine options tuned for PostgreSQL.

        Uses PostgreSQL's default ``READ COMMITTED`` isolation level so that
        SAVEPOINTs (``session.begin_nested()``) work correctly.  All bulk
        import / sync loops wrap each item in a SAVEPOINT; if one row fails
        only that SAVEPOINT is rolled back and the outer transaction stays
        healthy.  A final ``commit()`` persists everything that succeeded.
        """
        return {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_size": 10,
            "pool_timeout": 30,
            "max_overflow": 20,
        }

    # ------------------------------------------------------------------
    # High-level entry point
    # ------------------------------------------------------------------
    def ensure_running(self) -> bool:
        """Start PG if needed, provision role/databases. Returns True on success."""
        # If PG is already running (detected via psycopg2 or pg_isready), skip start attempt
        if self.is_running():
            print("[PostgresManager] PostgreSQL is already running.", flush=True)
            self.ensure_role_and_databases()
            return True

        # Try to start (requires local binaries / service)
        print("[PostgresManager] PostgreSQL not running, attempting to start...", flush=True)
        if not self.start_server():
            return False
        # Small pause to let connections stabilise
        time.sleep(1)
        self.ensure_role_and_databases()
        return True

    # ------------------------------------------------------------------
    # Sequence reset (fix for SQLite→PG migration desync)
    # ------------------------------------------------------------------
    def reset_all_sequences(self) -> bool:
        """Reset all PostgreSQL sequences to MAX(id)+1 to fix migration desync.

        When data is migrated from SQLite to PostgreSQL, rows are inserted with
        explicit IDs but the PostgreSQL sequences (used for auto-increment) don't
        get updated.  This causes duplicate-key errors on subsequent INSERTs.

        Call this once after table creation to fix the issue.
        """
        databases = [
            self.cfg["database"],
            self.cfg["database_users"],
            self.cfg["database_pages"],
            self.cfg["database_misc"],
        ]

        try:
            import psycopg2
            from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        except ImportError:
            print("[PostgresManager] psycopg2 not installed; cannot reset sequences.", flush=True)
            return False

        user = self.cfg["user"]
        password = self.cfg["password"]
        host = self.cfg["host"]
        port = self.cfg["port"]

        total_reset = 0

        for db_name in databases:
            try:
                conn = psycopg2.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    dbname=db_name,
                    connect_timeout=5,
                )
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                cur = conn.cursor()

                # Find all sequences and their owning columns
                cur.execute("""
                    SELECT
                        s.relname AS seq_name,
                        t.relname AS table_name,
                        a.attname AS column_name
                    FROM pg_class s
                    JOIN pg_depend d ON d.objid = s.oid
                    JOIN pg_class t ON t.oid = d.refobjid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                    WHERE s.relkind = 'S'
                      AND d.deptype = 'a'
                """)
                sequences = cur.fetchall()

                for seq_name, table_name, column_name in sequences:
                    try:
                        # Get the current max value in the table
                        cur.execute(f'SELECT COALESCE(MAX("{column_name}"), 0) FROM "{table_name}"')
                        max_val = cur.fetchone()[0] or 0
                        # Reset the sequence to max+1
                        new_start = max_val + 1
                        cur.execute(f"SELECT setval('{seq_name}', {new_start}, false)")
                        total_reset += 1
                    except Exception as e:
                        # Skip sequences that can't be reset (no big deal)
                        print(f"[PostgresManager]   Could not reset {seq_name}: {e}", flush=True)

                cur.close()
                conn.close()
            except Exception as e:
                print(f"[PostgresManager] Could not reset sequences on {db_name}: {e}", flush=True)

        if total_reset > 0:
            print(f"[PostgresManager] Reset {total_reset} sequences to fix migration desync.", flush=True)
        return True
