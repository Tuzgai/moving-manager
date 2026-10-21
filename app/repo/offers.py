from __future__ import annotations

import sqlite3


def list_for_house(conn: sqlite3.Connection, house_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM offers WHERE house_id=? ORDER BY created_at DESC", (house_id,)
    ).fetchall()


def add(conn: sqlite3.Connection, *, house_id: int, amount_cents: int,
        sent_date: str | None, expires_at: str | None, status: str,
        contingencies: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO offers(house_id, amount_cents, sent_date, expires_at, status, contingencies)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (house_id, amount_cents, sent_date, expires_at, status, contingencies),
    )
    return int(cur.lastrowid)


def list_docs(conn: sqlite3.Connection, offer_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT f.* FROM offer_files of JOIN files f ON f.id=of.file_id"
        " WHERE of.offer_id=?", (offer_id,),
    ).fetchall()


def attach_file(conn: sqlite3.Connection, offer_id: int, file_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO offer_files(offer_id, file_id) VALUES (?, ?)",
        (offer_id, file_id),
    )
