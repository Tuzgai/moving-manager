"""Global search: FTS5 over item titles, note bodies, and file names.

Results are grouped by kind so you can see at a glance which bucket a hit
came from. Each row deep-links back to the right page.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.deps import current_user, get_db
from app.repo import search as search_repo
from app.routes._common import page_ctx

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    q: str = "",
):
    results = search_repo.query(conn, q, limit=50)

    # Resolve each hit to a display row with a clickable href.
    rows_by_kind: dict[str, list[dict]] = {"item": [], "note": [], "file": []}
    for r in results:
        if r["kind"] == "item":
            it = conn.execute(
                "SELECT id, type, title FROM items WHERE id=?", (r["ref_id"],),
            ).fetchone()
            if not it:
                continue
            if it["type"] == "house":
                href, badge = f"/houses/{it['id']}", "House"
            elif it["type"] == "task":
                href, badge = f"/selling?task={it['id']}", "Task"
            else:
                href, badge = "/", "Item"
            rows_by_kind["item"].append({
                "title": it["title"], "snip": r["snip"], "href": href, "badge": badge,
            })
        elif r["kind"] == "note":
            parent = conn.execute(
                "SELECT i.id, i.type, i.title FROM notes n JOIN items i ON i.id = n.item_id"
                " WHERE n.id=?", (r["ref_id"],),
            ).fetchone()
            if not parent:
                continue
            if parent["type"] == "house":
                href = f"/houses/{parent['id']}"
            elif parent["type"] == "task":
                href = f"/selling?task={parent['id']}"
            else:
                href = "/"
            rows_by_kind["note"].append({
                "title": f"Note on {parent['title']}",
                "snip": r["snip"], "href": href, "badge": "Note",
            })
        elif r["kind"] == "file":
            rows_by_kind["file"].append({
                "title": r["title"], "snip": r["snip"],
                "href": f"/documents/file/{r['ref_id']}", "badge": "File",
            })

    total = sum(len(v) for v in rows_by_kind.values())
    ctx = page_ctx(request, conn, who, active="")
    ctx.update({
        "q": q, "rows_by_kind": rows_by_kind, "total": total,
        "section_labels": {"item": "Houses & tasks", "note": "Notes", "file": "Files"},
    })
    return _templates(request).TemplateResponse(request, "search.html", ctx)
