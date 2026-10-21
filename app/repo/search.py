from __future__ import annotations

import sqlite3


def query(conn: sqlite3.Connection, q: str, limit: int = 20) -> list[sqlite3.Row]:
    if not q.strip():
        return []
    # Prefix match on each term, auto-quoted to defuse FTS operators from user input.
    terms = [t for t in q.strip().split() if t]
    safe = " ".join(f'"{t.replace(chr(34), "")}"*' for t in terms)
    return conn.execute(
        "SELECT kind, ref_id, title, snippet(search_index, 3, char(2), char(3), '…', 10) AS snip"
        " FROM search_index WHERE search_index MATCH ? LIMIT ?",
        (safe, limit),
    ).fetchall()
