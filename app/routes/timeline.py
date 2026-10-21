"""Timeline: every key_date, grouped by month, buy/sell pills, link to item.

Also lets the user add a new date inline — this is the one place to see the
full move's schedule.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import current_user, get_db
from app.repo import key_dates as key_dates_repo
from app.routes._common import page_ctx

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


@router.get("/timeline", response_class=HTMLResponse)
def timeline(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    show: str = "upcoming",   # 'upcoming' | 'all'
):
    if show == "all":
        rows = conn.execute(
            "SELECT kd.*, i.title AS item_title, i.type AS item_type"
            " FROM key_dates kd LEFT JOIN items i ON i.id = kd.item_id"
            " ORDER BY on_date"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT kd.*, i.title AS item_title, i.type AS item_type"
            " FROM key_dates kd LEFT JOIN items i ON i.id = kd.item_id"
            " WHERE on_date >= date('now', 'localtime') ORDER BY on_date"
        ).fetchall()

    # Group by YYYY-MM, keeping chronological order via a list
    groups: dict[str, list] = defaultdict(list)
    order: list[str] = []
    for r in rows:
        key = r["on_date"][:7]
        if key not in groups:
            order.append(key)
        try:
            dt = datetime.strptime(r["on_date"][:10], "%Y-%m-%d")
            label = {"mon": dt.strftime("%b").upper(), "day": str(dt.day), "iso": r["on_date"][:10]}
        except ValueError:
            label = {"mon": "?", "day": r["on_date"][:10], "iso": r["on_date"]}
        groups[key].append({"date": label, "row": r})

    group_list = []
    for k in order:
        try:
            heading = datetime.strptime(k + "-01", "%Y-%m-%d").strftime("%B %Y")
        except ValueError:
            heading = k
        group_list.append({"heading": heading, "items": groups[k]})

    items = conn.execute(
        "SELECT id, type, title FROM items ORDER BY type, title"
    ).fetchall()

    ctx = page_ctx(request, conn, who, active="Timeline")
    ctx.update({
        "group_list": group_list, "items": items, "show": show,
        "total": len(rows),
    })
    return _templates(request).TemplateResponse(request, "timeline.html", ctx)


@router.post("/timeline/new")
def new_date(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    title: Annotated[str, Form()],
    on_date: Annotated[str, Form()],
    category: Annotated[str, Form()],
    sub: Annotated[str, Form()] = "",
    item_id: Annotated[str, Form()] = "",
):
    key_dates_repo.add(
        conn, title=title.strip() or "Date",
        on_date=on_date, category=category if category in ("buy", "sell") else "buy",
        sub=sub.strip(),
        item_id=int(item_id) if item_id.isdigit() else None,
    )
    return RedirectResponse(url="/timeline", status_code=303)


@router.post("/timeline/{date_id}/delete")
def delete_date(
    date_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    conn.execute("DELETE FROM key_dates WHERE id=?", (date_id,))
    return RedirectResponse(url="/timeline", status_code=303)
