"""Houses list, detail, and compare table.

The compare table highlights the "best" cell per numeric row. Which direction
is better varies by field (lower is better for price and $/sqft, higher for
sqft and ratings), so each comparable row carries a `direction` and we compute
the winning column index server-side.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import scrape
from app.deps import current_user, get_db
from app.models import House
from app.repo import items as items_repo
from app.repo import notes as notes_repo
from app.repo import offers as offers_repo
from app.repo import key_dates as key_dates_repo
from app.repo import contacts as contacts_repo
from app.routes._common import page_ctx

router = APIRouter()

STATUS_ORDER = ["Interested", "Toured", "Considering", "Offer out", "Under contract", "Passed"]


def _templates(request: Request):
    return request.app.state.templates


# ---- list page ----

@router.get("/houses", response_class=HTMLResponse)
def houses_list(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    status: str = "All",
    compare: Annotated[list[int] | None, Query()] = None,
):
    houses = items_repo.list_houses(conn, status=status)
    counts = items_repo.house_status_counts(conn)
    total = sum(counts.values())

    filters = [{"label": "All", "n": total, "pressed": status == "All"}]
    for s in STATUS_ORDER:
        filters.append({"label": s, "n": counts.get(s, 0), "pressed": status == s})

    # Compare takes up to 4 ids; fallback: first 4 of currently-filtered
    all_houses = items_repo.list_houses(conn)
    by_id = {h.id: h for h in all_houses}
    picked_ids = [i for i in (compare or []) if i in by_id][:4]
    if not picked_ids:
        picked_ids = [h.id for h in houses[:4]]
    picked = [by_id[i] for i in picked_ids]

    cmp_rows = _compare_rows(picked) if picked else []

    ctx = page_ctx(request, conn, who, active="Houses")
    ctx.update({
        "houses": houses,
        "status": status,
        "filters": filters,
        "all_houses": all_houses,
        "picked_ids": picked_ids,
        "cmp_houses": picked,
        "cmp_rows": cmp_rows,
    })
    return _templates(request).TemplateResponse(request, "houses_list.html", ctx)


def _dollars_per_sqft(h: House) -> int | None:
    if h.price_cents and h.sqft:
        return round((h.price_cents / 100) / h.sqft)
    return None


def _ratings_sum(h: House) -> float | None:
    vals = [v for v in h.ratings.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _compare_rows(houses: list[House]) -> list[dict]:
    """Return a list of row dicts with pre-computed cells and the winning index."""
    def row(label, raw_vals, *, direction: str = "none", font: str = "mono", fmt=lambda v: v if v is not None else "—"):
        # direction: "low" | "high" | "none" (none => no highlight)
        best = -1
        if direction in ("low", "high"):
            numeric = [(i, v) for i, v in enumerate(raw_vals) if isinstance(v, (int, float))]
            if numeric:
                best = min(numeric, key=lambda t: t[1])[0] if direction == "low" else max(numeric, key=lambda t: t[1])[0]
        cells = [{"v": fmt(v), "best": i == best} for i, v in enumerate(raw_vals)]
        return {"label": label, "cells": cells, "font": font}

    def dollars(v):
        return "—" if v is None else f"${v:,.0f}"

    def dollars_cents(v):
        return "—" if v is None else f"${(v // 100):,}"

    def bb(h: House):
        if h.beds is None and h.baths is None:
            return "—"
        b = f"{h.beds:g}" if h.beds is not None else "—"
        ba = f"{h.baths:g}" if h.baths is not None else "—"
        return f"{b} / {ba}"

    def rating(h: House):
        s = h.ratings.get("Stuart")
        a = h.ratings.get("Ashley")
        return f"{s if s is not None else '–'} / {a if a is not None else '–'}"

    rows = [
        row("List price",   [h.price_cents for h in houses], direction="low",  fmt=dollars_cents),
        row("Beds / baths", [h.beds for h in houses],        direction="high", fmt=lambda _: ""),  # placeholder; override cells below
        row("Finished sq ft", [h.sqft for h in houses],      direction="high", fmt=lambda v: "—" if v is None else f"{v:,}"),
        row("$ / sq ft",    [_dollars_per_sqft(h) for h in houses], direction="low", fmt=dollars),
        row("Garage",       [h.garage or "—" for h in houses], direction="none", font="sans"),
        row("Rating (S / A)", [_ratings_sum(h) for h in houses], direction="high", fmt=lambda _: ""),
        row("Best thing",   [h.best_thing or "—" for h in houses], direction="none", font="sans"),
        row("Worst thing",  [h.worst_thing or "—" for h in houses], direction="none", font="sans"),
    ]
    # Fill in display values for beds/baths and rating rows (we only used their numerics for ranking)
    for i, h in enumerate(houses):
        rows[1]["cells"][i]["v"] = bb(h)
        rows[5]["cells"][i]["v"] = rating(h)
    return rows


# ---- add from URL (must be registered before /houses/{house_id} since
# FastAPI matches in order and 'new' would otherwise fail to parse as int) ----

@router.get("/houses/new", response_class=HTMLResponse)
def new_house_form(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    url: str = "",
    error: str = "",
):
    """Step 1 is a URL box. If a URL is already present we show step 2 — a
    form pre-filled with what the scraper pulled out, letting the user fix
    anything before saving."""
    scraped = None
    if url:
        scraped = scrape.scrape(url)
    ctx = page_ctx(request, conn, who, active="Houses")
    ctx.update({
        "url": url, "scraped": scraped, "error": error,
        "statuses": STATUS_ORDER,
    })
    return _templates(request).TemplateResponse(request, "house_new.html", ctx)


@router.post("/houses/new")
def new_house_save(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    title: Annotated[str, Form()],
    url: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    price: Annotated[str, Form()] = "",
    beds: Annotated[str, Form()] = "",
    baths: Annotated[str, Form()] = "",
    sqft: Annotated[str, Form()] = "",
    year_built: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "Interested",
    image_url: Annotated[str, Form()] = "",
):
    def _int(s): return int(s) if s and s.lstrip("-").isdigit() else None
    def _float(s):
        try: return float(s) if s else None
        except ValueError: return None
    def _cents(s):
        s = (s or "").replace("$", "").replace(",", "").strip()
        if not s: return None
        try: return int(round(float(s) * 100))
        except ValueError: return None

    fields: dict = {}
    if url: fields["listing_url"] = url
    if address: fields["address"] = address
    if (c := _cents(price)) is not None: fields["price_cents"] = c
    if (b := _float(beds)) is not None: fields["beds"] = b
    if (ba := _float(baths)) is not None: fields["baths"] = ba
    if (sf := _int(sqft)) is not None: fields["sqft"] = sf
    if (yr := _int(year_built)) is not None: fields["year_built"] = yr
    if image_url: fields["other_links"] = [{"label": "Hero image", "url": image_url}]

    hid = items_repo.insert(
        conn, type_="house",
        title=title.strip() or "New house",
        status=status if status in STATUS_ORDER else "Interested",
        created_by=who, tags=["buy"], fields=fields,
    )
    return RedirectResponse(url=f"/houses/{hid}", status_code=303)


# ---- detail page ----

@router.get("/houses/{house_id}", response_class=HTMLResponse)
def house_detail(
    request: Request,
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    house = items_repo.get_house(conn, house_id)
    if not house:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/houses", status_code=302)

    notes = notes_repo.list_for(conn, house_id)
    offers = offers_repo.list_for_house(conn, house_id)
    offer_rows = []
    for o in offers:
        docs = offers_repo.list_docs(conn, o["id"])
        offer_rows.append({"offer": o, "docs": docs})
    dates = key_dates_repo.for_item(conn, house_id)
    people = contacts_repo.for_item(conn, house_id)

    # Files linked to this house (any role)
    files = conn.execute(
        "SELECT f.*, iif.role FROM item_files iif JOIN files f ON f.id=iif.file_id"
        " WHERE iif.item_id=? ORDER BY f.uploaded_at DESC",
        (house_id,),
    ).fetchall()
    photo_files = [f for f in files if f["role"] == "photo"]
    doc_files = [f for f in files if f["role"] != "photo"]

    facts = _facts_for(house)

    ctx = page_ctx(request, conn, who, active="Houses")
    ctx.update({
        "house": house,
        "notes": notes,
        "offer_rows": offer_rows,
        "dates": dates,
        "people": people,
        "photos": photo_files,
        "files": doc_files,
        "facts": facts,
        "statuses": STATUS_ORDER,
    })
    return _templates(request).TemplateResponse(request, "house_detail.html", ctx)


def _facts_for(h: House) -> list[dict[str, str]]:
    def dc(cents): return f"${(cents // 100):,}" if cents else "—"
    def num(v, suffix=""): return f"{v}{suffix}" if v is not None else "—"
    def bb():
        if h.beds is None and h.baths is None:
            return "—"
        return f"{h.beds:g} / {h.baths:g}"
    facts = [
        {"k": "List price", "v": dc(h.price_cents)},
        {"k": "Beds / baths", "v": bb()},
        {"k": "Finished sq ft", "v": f"{h.sqft:,}" if h.sqft else "—"},
        {"k": "Year built", "v": num(h.year_built)},
        {"k": "Lot", "v": h.lot or "—"},
        {"k": "Garage", "v": h.garage or "—"},
        {"k": "Taxes / yr", "v": dc(h.taxes_cents)},
        {"k": "Toured", "v": h.tour_date or "—"},
    ]
    for k, v in h.custom.items():
        facts.append({"k": k, "v": str(v)})
    return facts
