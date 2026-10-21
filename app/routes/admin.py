"""Admin endpoints: manual backup trigger. Tailnet-only, no auth."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from app.config import Config
from app.deps import get_config
from app.jobs import backup as backup_job

router = APIRouter()


@router.post("/admin/backup", response_class=PlainTextResponse)
def manual_backup(request: Request, cfg: Annotated[Config, Depends(get_config)]):
    out = backup_job.run_once(cfg.db_path, cfg.backup_dir, cfg.backup_keep)
    return f"Wrote {out.name}\n"
