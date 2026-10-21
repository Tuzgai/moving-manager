"""Phone tour-capture page.

Opens on a house, big "take photo" button that uses the phone's camera, a
quick-note textarea, four tag chips, a 1-5 gut rating. Save writes a note
with the rating and chip tags embedded, attaches any photos, and records
activity. Mobile-first layout — the whole thing fits in a phone viewport.
"""
from __future__ import annotations

import sqlite3
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from slugify import slugify

from app.config import Config
from app.deps import current_user, get_config, get_db
from app.repo import activity as activity_repo
from app.repo import files as files_repo
from app.repo import items as items_repo
from app.repo import notes as notes_repo

router = APIRouter()

CHIPS = ["Pro", "Con", "Question for agent", "Fix needed"]


def _templates(request: Request):
    return request.app.state.templates


@router.get("/capture", response_class=HTMLResponse)
def pick_house(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    """No house picked — show a list to tap into."""
    houses = items_repo.list_houses(conn)
    return _templates(request).TemplateResponse(request, "capture_pick.html", {
        "request": request, "houses": houses, "current_user": who,
    })


@router.get("/capture/{house_id}", response_class=HTMLResponse)
def capture(
    request: Request,
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    house = items_repo.get_house(conn, house_id)
    if not house:
        return RedirectResponse(url="/capture", status_code=302)
    # Count photos already attached today (local day), for the "This tour" line
    photos = conn.execute(
        "SELECT f.id, f.original_name, f.thumb_path FROM item_files iif"
        " JOIN files f ON f.id = iif.file_id"
        " WHERE iif.item_id=? AND iif.role='photo'"
        " AND date(f.uploaded_at, 'localtime') = date('now', 'localtime')"
        " ORDER BY f.uploaded_at DESC",
        (house_id,),
    ).fetchall()
    return _templates(request).TemplateResponse(request, "capture.html", {
        "request": request, "house": house, "current_user": who,
        "chips": CHIPS, "ratings": [1, 2, 3, 4, 5], "photos": photos,
    })


@router.post("/capture/{house_id}/save")
async def save(
    request: Request,
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str, Depends(current_user)],
    note: Annotated[str, Form()] = "",
    rating: Annotated[str, Form()] = "",
    chips: Annotated[list[str], Form()] = (),
    photos: Annotated[list[UploadFile], File()] = (),
):
    house = items_repo.get_house(conn, house_id)
    if not house:
        return RedirectResponse(url="/capture", status_code=302)

    # Save each photo to buy/<house-slug>/<original>, make thumb if image.
    photo_names: list[str] = []
    photo_ids: list[int] = []
    for p in photos or []:
        if not p or not p.filename:
            continue
        rel = PurePosixPath("buy") / slugify(house.title) / p.filename
        try:
            fid = files_repo.save_upload(conn, cfg.files_root, rel, p,
                                         uploaded_by=who, tags=["Tour", "Photos"])
        except files_repo.UploadTooLarge:
            raise HTTPException(status_code=413, detail=f"{p.filename} is over 50 MB")
        files_repo.link_to_item(conn, fid, house_id, role="photo")
        photo_names.append(p.filename)
        photo_ids.append(fid)

    # Compose a note body. Rating + chips are prefix lines; freeform text follows.
    prefix_lines = []
    if rating.isdigit() and 1 <= int(rating) <= 5:
        prefix_lines.append(f"**Gut rating:** {rating}/5")
        # Also stash the per-user rating on the house itself
        ratings = dict(house.ratings)
        ratings[who] = int(rating)
        fields = dict(house.to_fields())
        fields["ratings"] = ratings
        items_repo.update(conn, house_id, fields=fields)
    if chips:
        prefix_lines.append("**Tags:** " + ", ".join(chips))
    if photo_names:
        prefix_lines.append(f"**Photos:** {len(photo_names)}")
    body = "\n".join(prefix_lines + ([note.strip()] if note.strip() else []))

    if body:
        note_id = notes_repo.add(conn, item_id=house_id, author=who, body_md=body)
        for fid in photo_ids:
            conn.execute("INSERT OR IGNORE INTO note_files(note_id, file_id) VALUES (?, ?)",
                         (note_id, fid))
        activity_repo.log(
            conn, actor=who, verb="tour-note",
            text=f"captured a tour note on {house.title}", item_id=house_id,
        )

    return RedirectResponse(url=f"/capture/{house_id}?saved=1", status_code=303)
