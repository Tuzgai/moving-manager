from __future__ import annotations

import sqlite3


def all_(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()


def add(conn: sqlite3.Connection, *, name: str, role: str = "", phone: str = "",
        email: str = "", notes: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO contacts(name, role, phone, email, notes) VALUES (?, ?, ?, ?, ?)",
        (name, role, phone, email, notes),
    )
    return int(cur.lastrowid)


def link(conn: sqlite3.Connection, item_id: int, contact_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO item_contacts(item_id, contact_id) VALUES (?, ?)",
        (item_id, contact_id),
    )


def for_item(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT c.* FROM item_contacts ic JOIN contacts c ON c.id=ic.contact_id"
        " WHERE ic.item_id=? ORDER BY c.name", (item_id,),
    ).fetchall()
