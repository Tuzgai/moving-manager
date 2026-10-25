"""Quotes repo. Enforces 'only one chosen quote per task' in app code; the DB
also has a partial unique index as a backstop (see migration 001)."""
from __future__ import annotations

import sqlite3


def list_for_task(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT q.*, f.original_name AS file_name, f.stored_path AS file_path"
        " FROM quotes q LEFT JOIN files f ON f.id = q.file_id"
        " WHERE q.task_id=? ORDER BY q.created_at ASC",
        (task_id,),
    ).fetchall()


def add(conn: sqlite3.Connection, *, task_id: int, vendor: str, amount_cents: int,
        received_date: str | None = None, expires_at: str | None = None,
        note: str = "", file_id: int | None = None, chosen: bool = False) -> int:
    conn.execute("BEGIN")
    try:
        if chosen:
            conn.execute("UPDATE quotes SET chosen=0 WHERE task_id=?", (task_id,))
        cur = conn.execute(
            "INSERT INTO quotes(task_id, vendor, amount_cents, received_date,"
            " expires_at, note, file_id, chosen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, vendor, amount_cents, received_date, expires_at, note,
             file_id, 1 if chosen else 0),
        )
        conn.execute("COMMIT")
        return int(cur.lastrowid)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def choose(conn: sqlite3.Connection, *, task_id: int, quote_id: int) -> None:
    """Mark one quote chosen for a task; clear the others. Atomic."""
    conn.execute("BEGIN")
    try:
        conn.execute("UPDATE quotes SET chosen=0 WHERE task_id=?", (task_id,))
        conn.execute("UPDATE quotes SET chosen=1 WHERE id=? AND task_id=?",
                     (quote_id, task_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def clear_choice(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("UPDATE quotes SET chosen=0 WHERE task_id=?", (task_id,))


def chosen_total_cents(conn: sqlite3.Connection) -> int:
    """Sum of chosen quotes across every task — drives the Tasks header total."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM quotes WHERE chosen = 1"
    ).fetchone()
    return int(row["t"])
