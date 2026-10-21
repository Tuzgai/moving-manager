"""Context shared by every page: sidebar nav, user list, counts."""
from __future__ import annotations

import sqlite3
from typing import Any

from app.config import Config
from app.repo import items as items_repo


def nav(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The sidebar's six entries, with live counts.

    We query counts off the DB so they stay honest; where no count applies
    (Dashboard, Timeline), the count is an empty string.
    """
    house_n = items_repo.count_by_type(conn, "house")
    task_n = conn.execute(
        "SELECT COUNT(*) FROM items WHERE type='task' AND status NOT IN ('Done', 'Dropped')"
    ).fetchone()[0]
    doc_n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    contact_n = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    return [
        {"label": "Dashboard",  "href": "/",          "count": ""},
        {"label": "Houses",     "href": "/houses",    "count": str(house_n) if house_n else ""},
        {"label": "Selling",    "href": "/selling",   "count": str(task_n) if task_n else ""},
        {"label": "Documents",  "href": "/documents", "count": str(doc_n) if doc_n else ""},
        {"label": "Contacts",   "href": "/contacts",  "count": str(contact_n) if contact_n else ""},
        {"label": "Timeline",   "href": "/timeline",  "count": ""},
        {"label": "Tour capture", "href": "/capture", "count": ""},
    ]


def page_ctx(request, conn: sqlite3.Connection, current_user: str, *, active: str) -> dict[str, Any]:
    cfg: Config = request.app.state.config
    return {
        "request": request,
        "nav": nav(conn),
        "nav_active": active,
        "users": cfg.users,
        "current_user": current_user,
    }
