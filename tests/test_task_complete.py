"""Marking a task done flips its status."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.repo import items as items_repo


def test_complete_sets_status_done(tmp_path, monkeypatch):
    # Point the app at a throwaway DB + files_root for this test.
    import app.config as cfg_mod
    orig = cfg_mod.load

    def fake_load():
        c = orig()
        return cfg_mod.Config(
            host=c.host, port=c.port,
            data_dir=tmp_path / "data",
            files_root=tmp_path / "files",
            backup_dir=tmp_path / "backups",
            backup_keep=c.backup_keep, users=c.users,
        )

    monkeypatch.setattr(cfg_mod, "load", fake_load)

    with TestClient(app) as client:
        import sqlite3
        from app import db as db_mod
        conn = db_mod.connect(tmp_path / "data" / "db.sqlite")
        try:
            tid = items_repo.insert(
                conn, type_="task", title="Paint hallway",
                status="Not started", created_by="Stuart",
            )
        finally:
            conn.close()

        # HTMX call returns empty 200 so the row can be swapped out
        r = client.post(f"/tasks/{tid}/complete", headers={"hx-request": "true"})
        assert r.status_code == 200
        assert r.text == ""

        conn = db_mod.connect(tmp_path / "data" / "db.sqlite")
        try:
            it = items_repo.get(conn, tid)
        finally:
            conn.close()
        assert it.status == "Done"
