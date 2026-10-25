"""Snapshot + rotation of the SQLite DB.

The snapshot uses sqlite3's online backup API, producing a standalone .sqlite
that is safe to put in Dropbox. Rotation keeps the newest N by lexical name
(the filename is ISO-ordered so lexical == chronological).
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from app import db as db_mod
from app.jobs import backup


def test_snapshot_produces_a_readable_copy(tmp_path: Path):
    live = tmp_path / "live.sqlite"
    conn = db_mod.init(live)
    conn.execute("INSERT INTO contacts(name) VALUES ('Jamie')")
    conn.close()

    backup_dir = tmp_path / "backups"
    out = backup.snapshot(live, backup_dir)
    assert out.exists()
    assert out.parent == backup_dir

    # The snapshot opens cleanly and holds the row we just inserted.
    copy = sqlite3.connect(out)
    try:
        n = copy.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    finally:
        copy.close()
    assert n == 1


def test_rotate_keeps_newest_n(tmp_path: Path):
    # Fabricate 20 snapshots with dated names; the rotator should keep the 14
    # with the lexically-largest (i.e. newest) names.
    for day in range(1, 21):
        name = f"household-2026-10-{day:02d}-0300.sqlite"
        (tmp_path / name).write_text("x")
    stale = backup.rotate(tmp_path, keep=14)
    assert len(stale) == 6
    remaining = sorted(p.name for p in tmp_path.glob("household-*.sqlite"))
    assert remaining[0] == "household-2026-10-07-0300.sqlite"
    assert remaining[-1] == "household-2026-10-20-0300.sqlite"


def test_rotate_noop_when_under_cap(tmp_path: Path):
    for day in range(1, 5):
        (tmp_path / f"household-2026-10-{day:02d}-0300.sqlite").write_text("x")
    stale = backup.rotate(tmp_path, keep=14)
    assert stale == []
    assert len(list(tmp_path.glob("household-*.sqlite"))) == 4


def test_rotate_keep_zero_is_a_noop(tmp_path: Path):
    """keep=0 or negative is treated as 'do nothing' — the backup dir is never
    emptied by accident if someone misconfigures the keep count."""
    (tmp_path / "household-2026-10-01-0300.sqlite").write_text("x")
    assert backup.rotate(tmp_path, keep=0) == []
    assert backup.rotate(tmp_path, keep=-5) == []
    assert (tmp_path / "household-2026-10-01-0300.sqlite").exists()


def test_run_once_writes_then_rotates(tmp_path: Path):
    live = tmp_path / "live.sqlite"
    conn = db_mod.init(live)
    conn.close()
    backup_dir = tmp_path / "b"

    # Seed the dir with 20 existing snapshots.
    backup_dir.mkdir()
    for day in range(1, 21):
        (backup_dir / f"household-2026-10-{day:02d}-0300.sqlite").write_text("x")

    out = backup.run_once(live, backup_dir, keep=14)
    assert out.exists()
    # After writing one new + rotating to 14 total, dir should have exactly 14.
    assert len(list(backup_dir.glob("household-*.sqlite"))) == 14


def test_admin_backup_endpoint_accepts_get_and_post(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app import config as app_config

    real = app_config.load()
    cfg = real.__class__(**{**real.__dict__, "data_dir": tmp_path, "backup_dir": tmp_path / "b"})
    monkeypatch.setattr(app_config, "load", lambda: cfg)
    with TestClient(app) as c:
        for method in ("get", "post"):
            r = getattr(c, method)("/admin/backup")
            assert r.status_code == 200 and r.text.startswith("Wrote household-")
