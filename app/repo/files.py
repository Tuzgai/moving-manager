"""On-disk file storage with human-readable paths.

Path rules (see spec):
  buy/<house-slug>/<name>.<ext>
  sell/quotes/<task-slug>-<vendor-slug>.<ext>
  mortgage/..., taxes/..., etc.
  unlinked/<yyyy-mm>/<name>.<ext>  when uploaded without an item link

Collisions get a numeric suffix: foo.pdf, foo-2.pdf, foo-3.pdf.
"""
from __future__ import annotations

import mimetypes
import sqlite3
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from slugify import slugify


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
