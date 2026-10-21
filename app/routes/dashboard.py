"""Dashboard: four stat tiles, upcoming key dates, my tasks, recent activity.

Each tile is derived from live data so numbers never drift from the pages
they summarize (houses toured count the same rows as /houses, prep cost is
the same sum as the Selling header).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.deps import current_user, get_db
from app.models import Task
from app.repo import activity as activity_repo
from app.repo import items as items_repo
from app.repo import key_dates as key_dates_repo
from app.repo import quotes as quotes_repo
from app.routes._common import page_ctx

router = APIRouter()

TOURED_STATUSES = {"Toured", "Considering", "Offer out", "Under contract"}
IN_RUNNING_STATUSES = {"Considering", "Offer out", "Under contract"}
WAITING_STATUS = "Waiting"


def _templates(request: Request):
    return request.app.state.templates


def _target_list_date(conn: sqlite3.Connection) -> str | None:
    """Earliest key_date tagged 'sell' with the word 'listing' in its title.
    Falls back to the earliest sell key_date, else None."""
    row = conn.execute(
        "SELECT on_date FROM key_dates"
        " WHERE category='sell' AND LOWER(title) LIKE '%listing%'"
        " ORDER BY on_date LIMIT 1"
    ).fetchone()
    if row:
        return row["on_date"]
    row = conn.execute(
        "SELECT on_date FROM key_dates WHERE category='sell' ORDER BY on_date LIMIT 1"
    ).fetchone()
    return row["on_date"] if row else None


def _due_fg(iso: str | None) -> str:
    """Red if overdue or <= 7 days, amber if <= 30, grey otherwise."""
    if not iso:
        return "var(--ink-mute)"
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return "var(--ink-mute)"
    delta = (d - date.today()).days
    if delta <= 7:
        return "var(--warn-fg)"
    if delta <= 30:
        return "var(--amber-fg)"
    return "var(--ink-mute)"


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    # --- stat tiles ---
    houses = items_repo.list_houses(conn)
    toured = sum(1 for h in houses if h.status in TOURED_STATUSES)
    running = sum(1 for h in houses if h.status in IN_RUNNING_STATUSES)

    tasks = items_repo.list_tasks(conn)
    open_tasks = [t for t in tasks if t.status not in ("Done", "Dropped")]
    waiting_on_quotes = sum(1 for t in open_tasks if t.status == WAITING_STATUS or t.status == "Quoting")

    prep_cost_cents = quotes_repo.chosen_total_cents(conn)

    target = _target_list_date(conn)
    target_label = ""
    target_sub = ""
    if target:
        try:
            d = datetime.strptime(target[:10], "%Y-%m-%d").date()
            target_label = d.strftime("%b %-d")
        except (ValueError, Exception):
            try:
                target_label = datetime.strptime(target[:10], "%Y-%m-%d").strftime("%b %#d")
            except Exception:
                target_label = target
        days = (datetime.strptime(target[:10], "%Y-%m-%d").date() - date.today()).days
        target_sub = f"{days} days out" if days >= 0 else f"{-days} days past"

    stats = [
        {"label": "Houses toured", "value": str(toured),
         "sub": f"{running} still in the running"},
        {"label": "Open sell tasks", "value": str(len(open_tasks)),
         "sub": f"{waiting_on_quotes} waiting on quotes" if waiting_on_quotes else "none waiting on quotes"},
        {"label": "Prep cost", "value": _money_short(prep_cost_cents),
         "sub": "Sum of chosen quotes"},
        {"label": "Target list date", "value": target_label or "—",
         "sub": target_sub or "no sell dates set"},
    ]

    # --- coming up ---
    dates = key_dates_repo.upcoming(conn, limit=6)
    date_rows = []
    for d in dates:
        try:
            dt = datetime.strptime(d["on_date"][:10], "%Y-%m-%d").date()
            mon = dt.strftime("%b").upper()
            day = str(dt.day)
        except ValueError:
            mon, day = "", ""
        tag_bg, tag_fg = (
            ("#E3EEF9", "#1D4E89") if d["category"] == "buy" else ("#FDEBD3", "#7A4300")
        )
        date_rows.append({
            "mon": mon, "day": day, "title": d["title"],
            "sub": d["sub"], "tag": d["category"].capitalize(),
            "tag_bg": tag_bg, "tag_fg": tag_fg,
        })

    # --- my tasks ---
    mine = [
        t for t in open_tasks
        if t.assignee in (who, "Both")
    ]
    # Order by due_date (missing dates last)
    mine.sort(key=lambda t: t.due_date or "9999-99-99")
    my_task_rows = [
        {
            "id": t.id, "title": t.title,
            "sub": f"{t.area or '—'} · {t.priority or '—'}"
                   + (f" · {t.assignee}" if t.assignee == "Both" else ""),
            "due": _short_date(t.due_date),
            "due_fg": _due_fg(t.due_date),
        }
        for t in mine[:5]
    ]

    # --- recent activity ---
    activity = activity_repo.recent(conn, limit=5)

    ctx = page_ctx(request, conn, who, active="Dashboard")
    ctx.update({
        "stats": stats,
        "today_label": date.today().strftime("%A, %b %-d") if _supports_pct_dash() else date.today().strftime("%A, %b %#d"),
        "dates": date_rows,
        "my_tasks": my_task_rows,
        "activity": activity,
    })
    return _templates(request).TemplateResponse(request, "dashboard.html", ctx)


def _supports_pct_dash() -> bool:
    try:
        datetime.now().strftime("%-d")
        return True
    except ValueError:
        return False


def _short_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.strptime(iso[:10], "%Y-%m-%d")
    except ValueError:
        return iso
    try:
        return dt.strftime("%b %-d")
    except ValueError:
        return dt.strftime("%b %#d")


def _money_short(cents: int) -> str:
    if cents == 0:
        return "$0"
    dollars = cents / 100
    if dollars >= 1000:
        return f"${dollars:,.0f}"
    return f"${dollars:,.2f}"
