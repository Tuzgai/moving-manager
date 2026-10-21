"""Nightly SQLite snapshot via connection.backup().

Design notes:
  - We use sqlite3's online backup API (not VACUUM INTO) so the backup runs
    without blocking writers for more than small bursts. The result is a
    consistent, standalone .sqlite file safe for Dropbox.
  - Rotation keeps the newest N by filename sort (names are ISO-ish so lexical
    order == chronological).
  - Scheduled from app startup as an asyncio task; no cron needed.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def snapshot(db_path: Path, backup_dir: Path, *, now: datetime | None = None) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()
    out = backup_dir / f"household-{now:%Y-%m-%d-%H%M}.sqlite"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return out


def rotate(backup_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` snapshots. Returns the deleted paths."""
    if keep < 1:
        return []
    files = sorted(backup_dir.glob("household-*.sqlite"))
    stale = files[:-keep] if len(files) > keep else []
    for p in stale:
        p.unlink(missing_ok=True)
    return stale


def run_once(db_path: Path, backup_dir: Path, keep: int) -> Path:
    out = snapshot(db_path, backup_dir)
    rotate(backup_dir, keep)
    log.info("backup: wrote %s, keeping %d", out.name, keep)
    return out


async def scheduler(db_path: Path, backup_dir: Path, keep: int) -> None:
    """Runs run_once once a day, around 03:17 local time."""
    while True:
        now = datetime.now()
        target = now.replace(hour=3, minute=17, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await asyncio.to_thread(run_once, db_path, backup_dir, keep)
        except Exception:  # keep the loop alive
            log.exception("backup failed")
