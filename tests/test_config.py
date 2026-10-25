from __future__ import annotations

from pathlib import Path

from app import config


def test_scratch_env_moves_db_files_and_backups(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(config.SCRATCH_ENV, raising=False)
    live = config.load()

    monkeypatch.setenv(config.SCRATCH_ENV, str(tmp_path))
    cfg = config.load()
    root = tmp_path.resolve()
    assert cfg.db_path == root / "data" / "db.sqlite"
    assert cfg.files_root == root / "files"
    assert cfg.backup_dir == root / "backups"
    # Nothing about the scratch config may overlap the live paths.
    assert root not in live.db_path.parents
    # Unrelated settings are untouched.
    assert cfg.users == live.users and cfg.backup_keep == live.backup_keep
