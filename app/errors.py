"""Human-readable error responses instead of FastAPI's JSON.

- A failed form POST redirects back to the page it came from with ?error=...,
  which the page shows as a toast. The scroll-restore script keeps your place.
- A failed page load (bad URL, deleted item) renders a small error page.
- HTMX requests get the message as plain text for the client-side toast.
"""
from __future__ import annotations

import http
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

FIELD_LABELS = {
    "files": "a file", "title": "a title", "name": "a name", "amount": "an amount",
    "vendor": "a vendor", "on_date": "a date", "category": "a category", "body": "some text",
    "status": "a status",
}

DEFAULT_MESSAGES = {
    404: "That page doesn't exist — it may have been deleted.",
    413: "That file is too large (50 MB limit).",
}


def _field(err: dict) -> str:
    for part in reversed(err.get("loc", ())):
        if isinstance(part, str) and part not in ("body", "query", "path", "form"):
            return part
    return ""


def validation_message(exc: RequestValidationError) -> str:
    msgs = []
    for err in exc.errors():
        field = _field(err)
        if err.get("type") == "missing":
            msgs.append(f"Please add {FIELD_LABELS.get(field, field.replace('_', ' '))}.")
        else:
            msgs.append(f"The {field.replace('_', ' ') or 'form'} value doesn't look right.")
    return " ".join(dict.fromkeys(msgs)) or "Something in that form wasn't valid."


def _back_with_error(request: Request, message: str) -> RedirectResponse | None:
    """303 to the referring page with ?error=. Only the referer's path and
    query are reused, so this can't be turned into an open redirect."""
    ref = request.headers.get("referer")
    if request.method == "GET" or not ref:
        return None
    parts = urlsplit(ref)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "error"] + [("error", message)]
    return RedirectResponse(urlunsplit(("", "", parts.path or "/", urlencode(query), "")), status_code=303)


def error_response(request: Request, status: int, message: str):
    if request.headers.get("hx-request") == "true":
        return PlainTextResponse(message, status_code=status)
    back = _back_with_error(request, message)
    if back is not None:
        return back
    return request.app.state.templates.TemplateResponse(
        request, "error.html", {"request": request, "status": status, "message": message},
        status_code=status,
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # A non-numeric id in the URL is really a "no such page".
        if any(_field(e) and e.get("loc", ("",))[0] == "path" for e in exc.errors()):
            return error_response(request, 404, DEFAULT_MESSAGES[404])
        return error_response(request, 422, validation_message(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else ""
        if not detail or detail == http.HTTPStatus(exc.status_code).phrase:
            detail = DEFAULT_MESSAGES.get(exc.status_code, "Something went wrong with that request.")
        return error_response(request, exc.status_code, detail)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return error_response(
            request, 500,
            "Something went wrong on the server. Nothing was saved — try again, "
            "and if it keeps happening, check the logs.",
        )
