"""Documents page: tag sidebar, search, drag-and-drop upload, file table.

Uploads land under the configured files_root using human-readable paths:
  - Linked to a house  -> buy/<house-slug>/<name>
  - Linked to a task   -> sell/<task-slug>/<name>      (one level above quotes)
  - Unlinked           -> unlinked/<yyyy-mm>/<name>
Collisions get a numeric suffix. Images get a 400px JPEG thumbnail saved next
to the original so the browser can show previews without decoding a 10 MB JPG.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from slugify import slugify

from app.config import Config
from app.deps import current_user, get_config, get_db
from app.repo import activity as activity_repo
from app.repo import files as files_repo
from app.routes._common import page_ctx

router = APIRouter()

DEFAULT_TAGS = [
    "Offers", "Mortgage", "Quotes", "Inspection", "Disclosure",
    "Closing", "Insurance", "Taxes", "Records",
]

MAX_UPLOAD_BYTES = files_repo.MAX_UPLOAD_BYTES


def _templates(request: Request):
    return request.app.state.templates


def _parse_tags(raw: str) -> list[str]:
    """Comma- or newline-separated. Dedup while preserving order."""
    seen, out = set(), []
    for part in raw.replace("\n", ",").split(","):
        t = part.strip()
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out


@router.get("/documents", response_class=HTMLResponse)
def documents_list(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    cfg: Annotated[Config, Depends(get_config)],
    tag: str = "All",
    q: str = "",
):
    rows = files_repo.list_all(conn, tag=tag if tag != "All" else None, q=q or None)
    links = files_repo.linked_items(conn, [r["id"] for r in rows])

    files = []
    for r in rows:
        file_links = links.get(r["id"], [])
        files.append({
            "id": r["id"],
            "name": r["original_name"],
            "path": r["stored_path"],
            "tags": json.loads(r["tags"]) if r["tags"] else [],
            "linked": file_links,
            "added_by": r["uploaded_by"],
            "added_at": r["uploaded_at"],
            "size_bytes": r["size_bytes"],
            "mime": r["mime_type"],
            "thumb": r["thumb_path"],
        })

    counts = files_repo.tag_counts(conn)
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    tag_list = [{"name": "All", "n": total, "active": tag == "All"}]
    # Show seeded defaults first (even at count 0), then any extras from the DB
    seen = set()
    for name in DEFAULT_TAGS:
        tag_list.append({"name": name, "n": counts.get(name, 0), "active": tag == name})
        seen.add(name)
    for name, n in sorted(counts.items()):
        if name not in seen:
            tag_list.append({"name": name, "n": n, "active": tag == name})

    # Items for the "link to" dropdown on upload
    items = conn.execute(
        "SELECT id, type, title FROM items ORDER BY type, title"
    ).fetchall()

    ctx = page_ctx(request, conn, who, active="Documents")
    ctx.update({
        "files": files,
        "tag": tag,
        "q": q,
        "tag_list": tag_list,
        "items": items,
        "files_root": str(cfg.files_root),
        "total": total,
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    })
    return _templates(request).TemplateResponse(request, "documents.html", ctx)


@router.post("/documents/upload")
async def upload(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str, Depends(current_user)],
    files: Annotated[list[UploadFile], File()],
    tags: Annotated[str, Form()] = "",
    link_item_id: Annotated[str, Form()] = "",
):
    parsed_tags = _parse_tags(tags)
    link_id: int | None = int(link_item_id) if link_item_id.isdigit() else None

    # Resolve the link's folder once
    link_item = None
    if link_id:
        link_item = conn.execute(
            "SELECT id, type, title FROM items WHERE id=?", (link_id,)
        ).fetchone()

    for upload in files:
        if not upload or not upload.filename:
            continue
        rel = _pick_path(link_item, upload.filename)
        try:
            file_id = files_repo.save_upload(conn, cfg.files_root, rel, upload,
                                             uploaded_by=who, tags=parsed_tags)
        except files_repo.UploadTooLarge:
            raise HTTPException(status_code=413, detail=f"{upload.filename} is over {MAX_UPLOAD_BYTES // (1024*1024)} MB")
        if link_id:
            files_repo.link_to_item(conn, file_id, link_id)
        activity_repo.log(
            conn, actor=who, verb="uploaded-file",
            text=f"uploaded {upload.filename}" + (f" ({upload.filename.rsplit('.', 1)[-1].upper()})" if '.' in upload.filename else ""),
            item_id=link_id,
        )

    return RedirectResponse(url="/documents", status_code=303)


def _pick_path(link_item, filename: str) -> PurePosixPath:
    """Where on disk to save this upload, based on what it's linked to."""
    if link_item is None:
        return files_repo.unlinked_path(datetime.now().strftime("%Y-%m"), filename)
    if link_item["type"] == "house":
        return files_repo.house_path(link_item["title"], filename)
    if link_item["type"] == "task":
        return PurePosixPath("sell") / slugify(link_item["title"]) / filename
    return files_repo.generic_path("other", filename)


@router.get("/documents/file/{file_id}")
def serve_file(
    file_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
):
    row = conn.execute(
        "SELECT original_name, stored_path, mime_type FROM files WHERE id=?",
        (file_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    # stored_path was composed and sanitized by save_upload, never taken raw
    # from a request, so joining it to files_root is safe.
    path = cfg.files_root / row["stored_path"]
    if not path.exists():
        raise HTTPException(status_code=404)
    mime = row["mime_type"]
    return FileResponse(
        path, media_type=mime, filename=row["original_name"],
        content_disposition_type="inline" if files_repo.is_inline_safe(mime) else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/thumb/{file_id}")
def serve_thumb(
    file_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
):
    row = conn.execute(
        "SELECT thumb_path FROM files WHERE id=?", (file_id,),
    ).fetchone()
    if not row or not row["thumb_path"]:
        raise HTTPException(status_code=404)
    path = cfg.files_root / row["thumb_path"]
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg")
