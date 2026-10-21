"""Path generation for stored files, and collision suffixing.

Rules:
  buy/<house-slug>/<name>.<ext>
  sell/quotes/<task-slug>-<vendor-slug>.<ext>
  <folder>/<name>.<ext>   generic
  unlinked/<yyyy-mm>/<name>.<ext>

Collisions get a numeric suffix: foo.pdf -> foo-2.pdf -> foo-3.pdf, so a
restored-from-Dropbox file doesn't silently clobber an existing one.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.repo import files as files_repo


def test_house_path_slugifies_nickname():
    rel = files_repo.house_path("Blue cape!!", "Purchase Agreement.pdf")
    assert str(rel) == "buy/blue-cape/Purchase Agreement.pdf"


def test_quote_path_combines_task_and_vendor_slugs():
    rel = files_repo.quote_path("Refinish living room floors", "Vendor B", "estimate.pdf")
    assert str(rel) == "sell/quotes/refinish-living-room-floors-vendor-b.pdf"


def test_quote_path_handles_no_extension():
    rel = files_repo.quote_path("Floors", "Vendor A", "scan")
    # Falls back to .pdf since quotes are almost always PDFs
    assert str(rel).endswith(".pdf")


def test_generic_path_passes_through():
    rel = files_repo.generic_path("mortgage", "2026-10-statement.pdf")
    assert str(rel) == "mortgage/2026-10-statement.pdf"


def test_unlinked_path_buckets_by_month():
    rel = files_repo.unlinked_path("2026-10", "scan.pdf")
    assert str(rel) == "unlinked/2026-10/scan.pdf"


def test_ensure_unique_returns_same_path_when_empty(tmp_path: Path):
    rel = PurePosixPath("sell/quotes/floors-a.pdf")
    assert files_repo.ensure_unique(tmp_path, rel) == rel


def test_ensure_unique_suffixes_on_collision(tmp_path: Path):
    rel = PurePosixPath("sell/quotes/floors-a.pdf")
    (tmp_path / "sell" / "quotes").mkdir(parents=True)
    (tmp_path / rel).write_text("first")

    second = files_repo.ensure_unique(tmp_path, rel)
    assert str(second) == "sell/quotes/floors-a-2.pdf"

    # Create -2, then expect -3
    (tmp_path / second).write_text("second")
    third = files_repo.ensure_unique(tmp_path, rel)
    assert str(third) == "sell/quotes/floors-a-3.pdf"


def test_write_file_creates_parent_dirs(tmp_path: Path):
    import io
    rel = PurePosixPath("sell/quotes/x.pdf")
    size = files_repo.write_file(tmp_path, rel, io.BytesIO(b"hello world"))
    assert size == 11
    assert (tmp_path / rel).read_bytes() == b"hello world"


def test_guess_mime_pdf():
    assert files_repo.guess_mime("estimate.pdf") == "application/pdf"


def test_guess_mime_unknown_falls_back():
    assert files_repo.guess_mime("blob") == "application/octet-stream"
