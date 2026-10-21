from __future__ import annotations

import sqlite3


def upcoming(conn: sqlite3.Connection, limit: int = 6) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM key_dates WHERE on_date >= date('now')"
        " ORDER BY on_date ASC LIMIT ?", (limit,),
    ).fetchall()


def for_item(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM key_dates WHERE item_id=? ORDER BY on_date", (item_id,)
    ).fetchall()


def add(conn: sqlite3.Connection, *, title: str, on_date: str, category: str,
        sub: str = "", item_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO key_dates(title, on_date, category, sub, item_id)"
        " VALUES (?, ?, ?, ?, ?)",
        (title, on_date, category, sub, item_id),
    )
    return int(cur.lastrowid)
