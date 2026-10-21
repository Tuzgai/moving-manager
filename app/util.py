"""Small template-friendly helpers."""
from __future__ import annotations

from datetime import date, datetime


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
