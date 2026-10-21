"""Contacts page: a simple list of people with roles and contact info.

Not mocked, so the layout follows the spec's "simple list page" direction:
one card per contact, add form at the top, inline edit for details, and a
small "link to..." selector so a contact can be attached to a house or task.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import current_user, get_db
from app.repo import contacts as contacts_repo
from app.routes._common import page_ctx

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


@router.get("/contacts", response_class=HTMLResponse)
def contacts_list(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    rows = contacts_repo.all_(conn)
    items = conn.execute(
        "SELECT id, type, title FROM items ORDER BY type, title"
    ).fetchall()
    # Map contact_id -> [items]
    linked: dict[int, list[sqlite3.Row]] = {}
    for r in conn.execute(
        "SELECT ic.contact_id, i.id, i.type, i.title FROM item_contacts ic"
        " JOIN items i ON i.id = ic.item_id"
    ):
        linked.setdefault(r["contact_id"], []).append(r)

    ctx = page_ctx(request, conn, who, active="Contacts")
    ctx.update({"contacts": rows, "items": items, "linked": linked})
    return _templates(request).TemplateResponse(request, "contacts.html", ctx)


@router.post("/contacts/new")
def new_contact(
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    name: Annotated[str, Form()],
    role: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    link_item_id: Annotated[str, Form()] = "",
):
    cid = contacts_repo.add(
        conn, name=name.strip() or "Unnamed", role=role.strip(),
        phone=phone.strip(), email=email.strip(), notes=notes.strip(),
    )
    if link_item_id.isdigit():
        contacts_repo.link(conn, int(link_item_id), cid)
    return RedirectResponse(url="/contacts", status_code=303)


@router.post("/contacts/{contact_id}/edit")
def edit_contact(
    contact_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    name: Annotated[str, Form()],
    role: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    conn.execute(
        "UPDATE contacts SET name=?, role=?, phone=?, email=?, notes=? WHERE id=?",
        (name.strip() or "Unnamed", role.strip(), phone.strip(),
         email.strip(), notes.strip(), contact_id),
    )
    return RedirectResponse(url="/contacts", status_code=303)


@router.post("/contacts/{contact_id}/link")
def link_contact(
    contact_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    item_id: Annotated[str, Form()] = "",
):
    if item_id.isdigit():
        contacts_repo.link(conn, int(item_id), contact_id)
    return RedirectResponse(url="/contacts", status_code=303)


@router.post("/contacts/{contact_id}/unlink")
def unlink_contact(
    contact_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    item_id: Annotated[str, Form()],
):
    conn.execute(
        "DELETE FROM item_contacts WHERE contact_id=? AND item_id=?",
        (contact_id, int(item_id)),
    )
    return RedirectResponse(url="/contacts", status_code=303)


@router.post("/contacts/{contact_id}/delete")
def delete_contact(
    contact_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
    return RedirectResponse(url="/contacts", status_code=303)
