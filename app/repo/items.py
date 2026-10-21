"""CRUD over the generic `items` table + typed helpers for houses and tasks."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.models import House, Item, Task


# --- generic ---

def get(conn: sqlite3.Connection, item_id: int) -> Item | None:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return Item.from_row(row) if row else None


def list_by_type(conn: sqlite3.Connection, type_: str) -> list[Item]:
    rows = conn.execute(
        "SELECT * FROM items WHERE type = ? ORDER BY updated_at DESC", (type_,)
    ).fetchall()
    return [Item.from_row(r) for r in rows]


def count_by_type(conn: sqlite3.Connection, type_: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM items WHERE type = ?", (type_,)).fetchone()[0]


def insert(
    conn: sqlite3.Connection,
    *,
    type_: str,
    title: str,
    status: str,
    created_by: str,
    tags: list[str] | None = None,
    fields: dict[str, Any] | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO items(type, title, status, tags, fields, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (type_, title, status, json.dumps(tags or []), json.dumps(fields or {}), created_by),
    )
    return int(cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    title: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    sets, args = [], []
    if title is not None:
        sets.append("title = ?"); args.append(title)
    if status is not None:
        sets.append("status = ?"); args.append(status)
    if tags is not None:
        sets.append("tags = ?"); args.append(json.dumps(tags))
    if fields is not None:
        sets.append("fields = ?"); args.append(json.dumps(fields))
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    args.append(item_id)
    conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", args)


# --- houses ---

def list_houses(conn: sqlite3.Connection, status: str | None = None) -> list[House]:
    if status and status != "All":
        rows = conn.execute(
            "SELECT * FROM items WHERE type='house' AND status=? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM items WHERE type='house' ORDER BY updated_at DESC"
        ).fetchall()
    return [House.from_item(Item.from_row(r)) for r in rows]


def get_house(conn: sqlite3.Connection, item_id: int) -> House | None:
    it = get(conn, item_id)
    if not it or it.type != "house":
        return None
    return House.from_item(it)


def house_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM items WHERE type='house' GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


# --- tasks ---

def list_tasks(conn: sqlite3.Connection) -> list[Task]:
    rows = conn.execute(
        "SELECT * FROM items WHERE type='task' ORDER BY updated_at DESC"
    ).fetchall()
    return [Task.from_item(Item.from_row(r)) for r in rows]
