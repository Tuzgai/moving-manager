"""Loads config.toml (merging config.local.toml over it) once at startup."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    data_dir: Path
    files_root: Path
    backup_dir: Path
    backup_keep: int
    users: list[str]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite"


def _expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> Config:
    base = tomllib.loads((PROJECT_ROOT / "config.toml").read_text())
    local_path = PROJECT_ROOT / "config.local.toml"
    if local_path.exists():
        base = _deep_merge(base, tomllib.loads(local_path.read_text()))
    return Config(
        host=base["app"]["host"],
        port=int(base["app"]["port"]),
        data_dir=_expand(base["app"]["data_dir"]),
        files_root=_expand(base["storage"]["files_root"]),
        backup_dir=_expand(base["storage"]["backup_dir"]),
        backup_keep=int(base["storage"]["backup_keep"]),
        users=list(base["users"]["names"]),
    )
