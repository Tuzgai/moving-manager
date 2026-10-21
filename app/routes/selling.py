"""Selling page: tasks grouped (by area/status/assignee), task detail with
editable fields, quotes table (one 'chosen' radio per task), notes log.

Chosen-quote selection posts normally and we 303 back to the same task; the
atomic flip lives in the repo (clear others, set this one), with the partial
unique index as a DB-level backstop.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Config
from app.deps import current_user, get_config, get_db
from app.models import Task
from app.repo import activity as activity_repo
from app.repo import files as files_repo
from app.repo import items as items_repo
from app.repo import notes as notes_repo
from app.repo import quotes as quotes_repo
from app.routes._common import page_ctx

router = APIRouter()

OPEN_STATUSES = ["Not started", "Quoting", "Waiting", "Doing it ourselves"]
ALL_STATUSES = OPEN_STATUSES + ["Done", "Dropped"]
PRIORITIES = ["High", "Med", "Low"]

PRIO_DOT = {"High": "#B3261E", "Med": "#C77700", "Low": "#A9B0B9"}


def _templates(request: Request):
    return request.app.state.templates


def _assignees(users: list[str]) -> list[str]:
    return users + ["Both"]


def _group(tasks: list[Task], by: str) -> list[tuple[str, list[Task]]]:
    """Return [(group_label, [tasks]), ...] in a predictable order."""
    buckets: dict[str, list[Task]] = defaultdict(list)
    if by == "status":
        key = lambda t: t.status or "—"            # noqa: E731
        order = ALL_STATUSES
    elif by == "assignee":
        key = lambda t: t.assignee or "—"          # noqa: E731
        order = None  # alphabetical
    else:  # area (default)
        key = lambda t: t.area or "—"              # noqa: E731
        order = None
    for t in tasks:
        buckets[key(t)].append(t)
    if order:
        keys = [k for k in order if k in buckets] + [k for k in buckets if k not in order]
    else:
        keys = sorted(buckets.keys())
    return [(k, buckets[k]) for k in keys]


@router.get("/selling", response_class=HTMLResponse)
def selling(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    task: int | None = None,
    group_by: str = "area",
    show: str = "everyone",
    hide_done: int = 1,
):
    tasks = items_repo.list_tasks(conn)

    # "Mine" filter: tasks assigned to current user or Both
    if show == "mine":
        tasks = [t for t in tasks if t.assignee in (who, "Both")]
    if hide_done:
        tasks = [t for t in tasks if t.status not in ("Done", "Dropped")]

    groups = _group(tasks, group_by)

    # Pick the task to show: ?task=id, else the first task in the first group
    all_task_ids = [t.id for t in tasks]
    if task is None or task not in all_task_ids:
        task = all_task_ids[0] if all_task_ids else None

    sel: dict = {}
    if task is not None:
        sel_item = items_repo.get(conn, task)
        if sel_item and sel_item.type == "task":
            sel_task = Task.from_item(sel_item)
            qrows = quotes_repo.list_for_task(conn, task)
            sel = {
                "task": sel_task,
                "quotes": qrows,
                "notes": notes_repo.list_for(conn, task),
                "quote_count": len(qrows),
            }

    # Quote counts per task for the sidebar
    quote_counts = {
        r["task_id"]: r["n"]
        for r in conn.execute(
            "SELECT task_id, COUNT(*) AS n FROM quotes GROUP BY task_id"
        ).fetchall()
    }

    cfg = request.app.state.config
    ctx = page_ctx(request, conn, who, active="Selling")
    ctx.update({
        "groups": groups,
        "group_by": group_by,
        "show": show,
        "hide_done": hide_done,
        "sel": sel,
        "selected_id": task,
        "prio_dot": PRIO_DOT,
        "quote_counts": quote_counts,
        "statuses": ALL_STATUSES,
        "priorities": PRIORITIES,
        "assignees": _assignees(cfg.users),
        "total_cents": quotes_repo.chosen_total_cents(conn),
        "spent_cents": _spent_so_far(conn),
        "open_count": sum(1 for t in items_repo.list_tasks(conn) if t.status in OPEN_STATUSES),
        "done_count": sum(1 for t in items_repo.list_tasks(conn) if t.status == "Done"),
    })
    return _templates(request).TemplateResponse(request, "selling.html", ctx)


def _spent_so_far(conn: sqlite3.Connection) -> int:
    """Sum of chosen quotes for tasks marked Done. Rough but useful for the header."""
    row = conn.execute(
        "SELECT COALESCE(SUM(q.amount_cents), 0) AS t"
        " FROM quotes q JOIN items i ON i.id = q.task_id"
        " WHERE q.chosen = 1 AND i.status = 'Done'"
    ).fetchone()
    return int(row["t"])


# ---- actions ----

def _dollars_to_cents(s: str) -> int:
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return 0
    return int(round(float(s) * 100))


@router.post("/selling/tasks/new")
def new_task(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    title: Annotated[str, Form()],
    area: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Med",
    assignee: Annotated[str, Form()] = "Both",
    due_date: Annotated[str, Form()] = "",
):
    tid = items_repo.insert(
        conn, type_="task", title=title.strip() or "Untitled task",
        status="Not started", created_by=who, tags=["sell"],
        fields={"area": area, "priority": priority, "assignee": assignee, "due_date": due_date},
    )
    return RedirectResponse(url=f"/selling?task={tid}", status_code=303)


@router.post("/selling/{task_id}/update")
def update_task(
    task_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    title: Annotated[str, Form()],
    status: Annotated[str, Form()],
    area: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "Med",
    assignee: Annotated[str, Form()] = "Both",
    due_date: Annotated[str, Form()] = "",
):
    it = items_repo.get(conn, task_id)
    if not it or it.type != "task":
        return RedirectResponse(url="/selling", status_code=303)
    fields = dict(it.fields)
    fields.update(area=area, priority=priority, assignee=assignee, due_date=due_date)
    items_repo.update(conn, task_id, title=title, status=status, fields=fields)
    return RedirectResponse(url=f"/selling?task={task_id}", status_code=303)


@router.post("/selling/{task_id}/notes/new")
def add_note(
    task_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    body: Annotated[str, Form()],
):
    body = (body or "").strip()
    if body:
        notes_repo.add(conn, item_id=task_id, author=who, body_md=body)
        it = items_repo.get(conn, task_id)
        if it:
            activity_repo.log(
                conn, actor=who, verb="added-note",
                text=f"added a note to {it.title}", item_id=task_id,
            )
    return RedirectResponse(url=f"/selling?task={task_id}", status_code=303)


@router.post("/selling/{task_id}/quotes/new")
async def add_quote(
    task_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str, Depends(current_user)],
    vendor: Annotated[str, Form()],
    amount: Annotated[str, Form()],
    received_date: Annotated[str, Form()] = "",
    expires_at: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    document: Annotated[UploadFile | None, File()] = None,
):
    cents = _dollars_to_cents(amount)
    file_id: int | None = None

    # Save the attached document, if any. Lives under sell/quotes/<slug>.<ext>
    if document is not None and document.filename:
        it = items_repo.get(conn, task_id)
        task_slug = (it.title if it else f"task-{task_id}")
        rel = files_repo.quote_path(task_slug, vendor, document.filename)
        try:
            file_id = files_repo.save_upload(conn, cfg.files_root, rel, document,
                                             uploaded_by=who, tags=["Quotes"])
        except files_repo.UploadTooLarge:
            raise HTTPException(status_code=413, detail=f"{document.filename} is over 50 MB")
        # Also expose it on the task so the Documents page can show "linked to <task>"
        files_repo.link_to_item(conn, file_id, task_id, role="quote_doc")

    quotes_repo.add(
        conn, task_id=task_id,
        vendor=vendor.strip() or "Vendor",
        amount_cents=cents,
        received_date=received_date or None,
        expires_at=expires_at or None,
        note=note.strip(),
        file_id=file_id,
    )
    it = items_repo.get(conn, task_id)
    if it:
        activity_repo.log(
            conn, actor=who, verb="added-quote",
            text=f"added a quote ({vendor}, ${cents // 100:,}) to {it.title}",
            item_id=task_id,
        )
    return RedirectResponse(url=f"/selling?task={task_id}", status_code=303)


@router.post("/selling/{task_id}/delete")
def delete_task(
    task_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    """Removes the task, its quotes and notes. Quote files stay in Documents."""
    it = items_repo.get(conn, task_id)
    if it and it.type == "task":
        conn.execute("DELETE FROM items WHERE id=?", (task_id,))
        activity_repo.log(conn, actor=who, verb="deleted", text=f"deleted task {it.title}")
    return RedirectResponse(url="/selling", status_code=303)


@router.post("/selling/{task_id}/complete")
def complete_task(
    task_id: int,
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    """Mark a task Done. If called via HTMX returns an empty 200 so the
    caller can swap/remove the row; otherwise redirects back where we came
    from (so the plain-HTML form in /selling still works)."""
    from fastapi.responses import HTMLResponse
    it = items_repo.get(conn, task_id)
    if it and it.type == "task":
        items_repo.update(conn, task_id, status="Done")
        activity_repo.log(conn, actor=who, verb="completed-task",
                          text=f"marked {it.title} as done", item_id=task_id)
    if request.headers.get("hx-request") == "true":
        return HTMLResponse("", status_code=200)
    return RedirectResponse(url=request.headers.get("referer", "/"), status_code=303)


@router.post("/selling/{task_id}/quotes/choose")
def choose_quote(
    task_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    quote_id: Annotated[str, Form()],  # 'none' or integer
):
    if quote_id == "none" or not quote_id:
        quotes_repo.clear_choice(conn, task_id)
    else:
        quotes_repo.choose(conn, task_id=task_id, quote_id=int(quote_id))
    return RedirectResponse(url=f"/selling?task={task_id}", status_code=303)
