"""SQLite connection + numbered-migrations runner.

Design notes:
  - WAL mode: concurrent reader + one writer, far fewer "database is locked" errors
    for a web app that occasionally runs a backup. Must NOT live inside Dropbox.
  - foreign_keys ON: SQLite ships with FK checks disabled; we need them for CASCADE.
  - One connection per request via FastAPI dependency (see deps.py); sqlite3 is thread-
    safe at the module level but each connection must stick to one thread.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may construct the Depends-provided conn
    # in a worker thread (for sync endpoints) and then hand it to the event-
    # loop thread (for async endpoints). We never share one connection across
    # concurrent requests — each request gets its own — so this is safe.
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster
    return conn


def _ensure_schema_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply any pending numbered migrations. Returns the versions applied."""
    _ensure_schema_table(conn)
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    pending = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in applied:
            continue
        sql = path.read_text()
        # executescript auto-commits any pending txn; just run it, then stamp the version.
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        pending.append(version)
    return pending


def init(db_path: Path) -> sqlite3.Connection:
    """Open the live DB (creating the directory if needed) and run migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    migrate(conn)
    return conn
