"""Escaping, path sanitizing, timestamps, and the seed guard."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import pytest

from app import db as db_mod
from app.repo import files as files_repo
from app.util import highlight_snippet, local_dt, md


def test_markdown_renders_formatting_and_escapes_html():
    out = str(md("**Gut rating:** 4/5\n<script>alert(1)</script>"))
    assert "<strong>Gut rating:</strong>" in out
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_refuses_javascript_links():
    out = str(md("[click](javascript:alert(1))"))
    assert "<a " not in out  # left as plain text, not turned into a link


def test_snippet_escapes_note_text_but_keeps_highlight():
    out = str(highlight_snippet("<img src=x onerror=alert(1)> \x02basement\x03 dry"))
    assert "<img" not in out
    assert "<mark>basement</mark>" in out


def test_safe_rel_strips_traversal_and_dotfiles():
    assert str(files_repo.safe_rel(PurePosixPath("buy/blue-cape/../../../etc/passwd"))) == "buy/blue-cape/etc/passwd"
    assert str(files_repo.safe_rel(PurePosixPath("buy/x/..\\..\\evil.pdf"))) == "buy/x/evil.pdf"
    assert str(files_repo.safe_rel(PurePosixPath("buy/x/.bashrc"))) == "buy/x/bashrc"


class _Upload:
    def __init__(self, name: str, data: bytes, ctype: str = "application/pdf"):
        self.filename = name
        self.file = io.BytesIO(data)
        self.content_type = ctype


def test_save_upload_stays_inside_root(tmp_path: Path):
    conn = db_mod.init(tmp_path / "db.sqlite")
    root = tmp_path / "files"
    fid = files_repo.save_upload(
        conn, root, PurePosixPath("buy/x") / "../../../escape.pdf", _Upload("../../../escape.pdf", b"x"),
        uploaded_by="Stuart", tags=[],
    )
    stored = conn.execute("SELECT stored_path FROM files WHERE id=?", (fid,)).fetchone()[0]
    assert (root / stored).resolve().is_relative_to(root.resolve())
    assert not (tmp_path / "escape.pdf").exists()
    conn.close()


def test_save_upload_rejects_oversize(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(files_repo, "MAX_UPLOAD_BYTES", 10)
    conn = db_mod.init(tmp_path / "db.sqlite")
    root = tmp_path / "files"
    with pytest.raises(files_repo.UploadTooLarge):
        files_repo.save_upload(conn, root, PurePosixPath("a/big.pdf"), _Upload("big.pdf", b"x" * 11),
                               uploaded_by="Stuart", tags=[])
    assert not (root / "a" / "big.pdf").exists()
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    conn.close()


def test_inline_safe_excludes_html_and_svg():
    assert files_repo.is_inline_safe("application/pdf")
    assert files_repo.is_inline_safe("image/jpeg")
    assert not files_repo.is_inline_safe("image/svg+xml")
    assert not files_repo.is_inline_safe("text/html")


def test_local_dt_converts_utc_to_local():
    utc_now = datetime.now(timezone.utc).replace(microsecond=0)
    expected = utc_now.astimezone().strftime("%I:%M %p").lstrip("0").lower()
    assert local_dt(utc_now.strftime("%Y-%m-%d %H:%M:%S")).endswith(expected)


def test_local_dt_labels_yesterday():
    y = datetime.now(timezone.utc) - timedelta(days=1)
    assert local_dt(y.strftime("%Y-%m-%d %H:%M:%S")).startswith(("Yesterday", "Today"))


def test_seed_refuses_to_wipe_existing_data(tmp_path, monkeypatch):
    import app.config as cfg_mod
    from scripts import seed

    real = cfg_mod.load()
    fake = cfg_mod.Config(
        host=real.host, port=real.port, data_dir=tmp_path, files_root=tmp_path / "f",
        backup_dir=tmp_path / "b", backup_keep=14, users=real.users,
    )
    monkeypatch.setattr(seed.app_config, "load", lambda: fake)

    assert seed.main([]) == 0           # empty DB: seeds
    assert seed.main([]) == 1           # has data: refuses
    conn = db_mod.connect(fake.db_path)
    n = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()
    assert n > 0
    assert seed.main(["--force"]) == 0  # explicit wipe still possible
