from __future__ import annotations

import sqlite3


def recent(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM activity ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def log(conn: sqlite3.Connection, *, actor: str, verb: str, text: str,
        item_id: int | None = None, created_at: str | None = None) -> int:
    if created_at:
        cur = conn.execute(
            "INSERT INTO activity(actor, verb, text, item_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (actor, verb, text, item_id, created_at),
        )
    else:
        cur = conn.execute(
            "INSERT INTO activity(actor, verb, text, item_id) VALUES (?, ?, ?, ?)",
            (actor, verb, text, item_id),
        )
    return int(cur.lastrowid)
