from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import db


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.init(tmp_path / "test.sqlite")
    try:
        yield c
    finally:
        c.close()
