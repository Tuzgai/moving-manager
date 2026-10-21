"""On-disk file storage with human-readable paths.

Path rules (see spec):
  buy/<house-slug>/<name>.<ext>
  sell/quotes/<task-slug>-<vendor-slug>.<ext>
  mortgage/..., taxes/..., etc.
  unlinked/<yyyy-mm>/<name>.<ext>  when uploaded without an item link

Collisions get a numeric suffix: foo.pdf, foo-2.pdf, foo-3.pdf.
"""
from __future__ import annotations

import json
import mimetypes
import sqlite3
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from slugify import slugify

IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"}
THUMB_LONG_EDGE = 400          # px
THUMB_QUALITY = 85


def ensure_unique(root: Path, rel: PurePosixPath) -> PurePosixPath:
    """If `root/rel` exists, return `rel` with a numeric suffix on the stem."""
    full = root / rel
    if not full.exists():
        return rel
    stem, suffix = PurePosixPath(rel.name).stem, PurePosixPath(rel.name).suffix
    parent = rel.parent
    for n in range(2, 10_000):
        candidate = parent / f"{stem}-{n}{suffix}"
        if not (root / candidate).exists():
            return candidate
    raise RuntimeError(f"too many collisions for {rel}")


def house_path(house_slug: str, filename: str) -> PurePosixPath:
    return PurePosixPath("buy") / slugify(house_slug) / filename


def quote_path(task_slug: str, vendor: str, filename: str) -> PurePosixPath:
    stem = PurePosixPath(filename).stem
    ext = PurePosixPath(filename).suffix
    name = f"{slugify(task_slug)}-{slugify(vendor)}"
    # If the uploaded name already looks like a quote (ends in .pdf, etc), keep ext
    return PurePosixPath("sell") / "quotes" / f"{name}{ext or '.pdf'}"


def generic_path(folder: str, filename: str) -> PurePosixPath:
    return PurePosixPath(folder) / filename


def unlinked_path(year_month: str, filename: str) -> PurePosixPath:
    return PurePosixPath("unlinked") / year_month / filename


def write_file(root: Path, rel: PurePosixPath, source: BinaryIO) -> int:
    """Writes source bytes to root/rel, returns bytes written."""
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as f:
        while chunk := source.read(1024 * 1024):
            f.write(chunk)
            size += len(chunk)
    return size


def insert(
    conn: sqlite3.Connection,
    *,
    original_name: str,
    stored_path: str,
    size_bytes: int,
    mime_type: str,
    tags: str,          # JSON string
    uploaded_by: str,
    thumb_path: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO files(original_name, stored_path, size_bytes, mime_type,"
        " tags, uploaded_by, thumb_path)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (original_name, stored_path, size_bytes, mime_type, tags, uploaded_by, thumb_path),
    )
    return int(cur.lastrowid)


def guess_mime(name: str) -> str:
    mt, _ = mimetypes.guess_type(name)
    return mt or "application/octet-stream"


# --- listing / filtering ---

def list_all(conn: sqlite3.Connection, *, tag: str | None = None,
             q: str | None = None, limit: int = 200) -> list[sqlite3.Row]:
    """Return files, newest first. Optional filters: a tag (JSON contains),
    a search query (LIKE on name + tags)."""
    where, args = [], []
    if tag and tag != "All":
        # tags column is a JSON array string like '["Quotes","Offers"]'.
        # Match on the quoted token so Quote doesn't match Quotes-of-interest etc.
        where.append("tags LIKE ?")
        args.append(f'%"{tag}"%')
    if q:
        where.append("(original_name LIKE ? OR tags LIKE ?)")
        args.extend([f"%{q}%", f"%{q}%"])
    sql = "SELECT * FROM files"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY uploaded_at DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def tag_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Fan out the JSON tags column and tally."""
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT tags FROM files"):
        try:
            tags = json.loads(row["tags"])
        except Exception:
            continue
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
    return counts


def linked_items(conn: sqlite3.Connection, file_ids: Iterable[int]) -> dict[int, list[sqlite3.Row]]:
    """Return {file_id: [items]} for all files passed in. One query, grouped."""
    ids = list(file_ids)
    if not ids:
        return {}
    qmarks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT iif.file_id, i.id, i.type, i.title FROM item_files iif"
        f" JOIN items i ON i.id = iif.item_id WHERE iif.file_id IN ({qmarks})",
        ids,
    ).fetchall()
    out: dict[int, list[sqlite3.Row]] = {}
    for r in rows:
        out.setdefault(r["file_id"], []).append(r)
    return out


def link_to_item(conn: sqlite3.Connection, file_id: int, item_id: int, role: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO item_files(item_id, file_id, role) VALUES (?, ?, ?)",
        (item_id, file_id, role),
    )


# --- thumbnails ---

def is_image(mime: str) -> bool:
    return mime in IMAGE_MIMES


def make_thumbnail(root: Path, rel: PurePosixPath) -> PurePosixPath | None:
    """Generate a 400px-long-edge JPEG thumbnail next to the original.
    Returns the thumb's relative path, or None if Pillow couldn't open it.
    Thumb filename: <stem>.thumb.jpg. Idempotent — safe to call again."""
    from PIL import Image, UnidentifiedImageError  # local import keeps startup light

    src = root / rel
    thumb_rel = rel.with_name(f"{PurePosixPath(rel.name).stem}.thumb.jpg")
    thumb_abs = root / thumb_rel
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_LONG_EDGE, THUMB_LONG_EDGE))
            im.save(thumb_abs, "JPEG", quality=THUMB_QUALITY)
    except (UnidentifiedImageError, OSError):
        return None
    return thumb_rel
