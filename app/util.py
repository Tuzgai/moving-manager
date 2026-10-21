"""Small template-friendly helpers."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from markdown_it import MarkdownIt
from markupsafe import Markup, escape

# html=False makes markdown-it escape any raw HTML in notes; its default link
# validator already refuses javascript:/vbscript:/data: URLs.
_md = MarkdownIt("commonmark", {"html": False, "breaks": True})


def md(text: str | None) -> Markup:
    return Markup(_md.render(text or ""))


def _to_local(s: str | None) -> datetime | None:
    """SQLite datetime('now') strings are UTC; convert to the server's local zone."""
    if not s:
        return None
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone()


def local_dt(s: str | None) -> str:
    dt = _to_local(s)
    if dt is None:
        return s or ""
    clock = dt.strftime("%I:%M %p").lstrip("0").lower()
    today = date.today()
    if dt.date() == today:
        return f"Today, {clock}"
    if dt.date() == today - timedelta(days=1):
        return f"Yesterday, {clock}"
    day = f"{dt.strftime('%b')} {dt.day}"
    if dt.year != today.year:
        day += f", {dt.year}"
    return f"{day}, {clock}"


def local_date(s: str | None) -> str:
    dt = _to_local(s)
    if dt is None:
        return (s or "")[:10]
    out = f"{dt.strftime('%b')} {dt.day}"
    return out if dt.year == date.today().year else f"{out}, {dt.year}"


def highlight_snippet(snip: str | None) -> Markup:
    """FTS snippets carry \\x02/\\x03 around matches. Escape the user text
    first, then turn the markers into <mark> tags."""
    safe = str(escape(snip or ""))
    return Markup(safe.replace("\x02", "<mark>").replace("\x03", "</mark>"))


def money(cents: int | None) -> str:
    if cents is None:
        return ""
    dollars = cents / 100
    if dollars >= 1000 and dollars == int(dollars):
        # Shorthand: $365,000 -> "$365k" in list views
        return f"${dollars:,.0f}"
    return f"${dollars:,.2f}"


def money_short(cents: int | None) -> str:
    if cents is None:
        return ""
    d = cents // 100
    if d >= 1000:
        return f"${d // 1000}k"
    return f"${d}"


def fmt_date(iso: str | None, fmt: str = "%b %-d") -> str:
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso[:10], "%Y-%m-%d")
    except ValueError:
        return iso
    # %-d is POSIX; Windows wants %#d. Keep this file working on both.
    try:
        return dt.strftime(fmt)
    except ValueError:
        return dt.strftime(fmt.replace("%-", "%#"))


def mon_day(iso: str | None) -> tuple[str, str]:
    if not iso:
        return "", ""
    try:
        dt = datetime.strptime(iso[:10], "%Y-%m-%d")
    except ValueError:
        return "", ""
    return dt.strftime("%b").upper(), str(dt.day)


def initial_of(name: str) -> str:
    return name[:1].upper() if name else "?"


def avatar_colors(name: str) -> tuple[str, str]:
    """Deterministic avatar bg/fg for a user name. Matches mockup palette for
    the two seeded users; everyone else gets a neutral grey."""
    palette = {
        "Stuart": ("#D6ECE5", "#164F42"),
        "Ashley": ("#E6E0F5", "#4A3480"),
    }
    return palette.get(name, ("#EEF0F2", "#3D444D"))


def days_from_today(iso: str) -> int:
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (d - date.today()).days
