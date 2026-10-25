"""FastAPI entry point.

Startup wiring:
  - Load config (config.toml + optional config.local.toml).
  - Ensure the live DB exists, is in WAL mode, and migrations are applied.
  - Mount static files, templates (with util filters registered).
  - Register routers for each screen.
  - Launch the backup scheduler as a background task.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config as app_config
from app import db
from app.jobs.backup import scheduler as backup_scheduler
from app.util import (
    avatar_colors, days_from_today, fmt_date, initial_of, local_date, local_dt, md, mon_day,
    money, money_short,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

PROJECT_ROOT = app_config.PROJECT_ROOT


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = app_config.load()
    app.state.config = cfg

    conn = db.init(cfg.db_path)
    conn.close()

    import asyncio
    task = asyncio.create_task(backup_scheduler(cfg.db_path, cfg.backup_dir, cfg.backup_keep))
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(lifespan=lifespan, title="Household Hub")

from app import errors  # noqa: E402

errors.install(app)

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))
for name, fn in {
    "money": money, "money_short": money_short, "fmt_date": fmt_date,
    "mon_day": mon_day, "initial_of": initial_of, "avatar_colors": avatar_colors,
    "days_from_today": days_from_today, "local_dt": local_dt, "local_date": local_date,
    "md": md,
}.items():
    templates.env.filters[name] = fn
# Cache-buster for app.css: browsers (phones especially) otherwise keep a
# stale stylesheet after an update. Changes whenever the file changes.
templates.env.globals["css_v"] = int((PROJECT_ROOT / "app" / "static" / "app.css").stat().st_mtime)
app.state.templates = templates

app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")), name="static")


# --- routers ---
from app.routes import (  # noqa: E402
    admin, capture, contacts, dashboard, documents, houses, search, tasks, timeline,
)

app.include_router(dashboard.router)
app.include_router(houses.router)
app.include_router(tasks.router)
app.include_router(documents.router)
app.include_router(capture.router)
app.include_router(contacts.router)
app.include_router(timeline.router)
app.include_router(search.router)
app.include_router(admin.router)


@app.post("/set-user")
async def set_user(request: Request):
    """Sidebar user picker posts here. Sets the cookie and bounces back."""
    from fastapi import Form
    form = await request.form()
    who = form.get("who", "")
    cfg = request.app.state.config
    if who not in cfg.users:
        who = cfg.users[0]
    referer = request.headers.get("referer", "/")
    resp = RedirectResponse(url=referer, status_code=303)
    resp.set_cookie("who", who, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp
