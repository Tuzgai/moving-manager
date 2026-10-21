from __future__ import annotations

import sqlite3


def list_for(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM notes WHERE item_id=? ORDER BY created_at DESC",
        (item_id,),
    ).fetchall()


def add(conn: sqlite3.Connection, *, item_id: int, author: str, body_md: str,
        created_at: str | None = None) -> int:
    if created_at:
        cur = conn.execute(
            "INSERT INTO notes(item_id, author, body_md, created_at) VALUES (?, ?, ?, ?)",
            (item_id, author, body_md, created_at),
        )
    else:
        cur = conn.execute(
            "INSERT INTO notes(item_id, author, body_md) VALUES (?, ?, ?)",
            (item_id, author, body_md),
        )
    return int(cur.lastrowid)
