"""FastAPI dependencies: DB connection per request + current user from cookie."""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import Cookie, Depends, Request

from app import db
from app.config import Config

USER_COOKIE = "who"


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_db(cfg: Annotated[Config, Depends(get_config)]):
    conn = db.connect(cfg.db_path)
    try:
        yield conn
    finally:
        conn.close()


def current_user(
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str | None, Cookie(alias=USER_COOKIE)] = None,
) -> str:
    """Returns the cookie's user if it's a configured name, else the first user."""
    if who and who in cfg.users:
        return who
    return cfg.users[0]
