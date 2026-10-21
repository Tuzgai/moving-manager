"""Houses list, detail, and compare table.

The compare table highlights the "best" cell per numeric row. Which direction
is better varies by field (lower is better for price and $/sqft, higher for
sqft and ratings), so each comparable row carries a `direction` and we compute
the winning column index server-side.
"""
from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from slugify import slugify

from app import scrape
from app.config import Config
from app.deps import current_user, get_config, get_db
from app.models import House
from app.repo import activity as activity_repo
from app.repo import files as files_repo
from app.repo import items as items_repo
from app.repo import notes as notes_repo
from app.repo import offers as offers_repo
from app.repo import key_dates as key_dates_repo
from app.repo import contacts as contacts_repo
from app.routes._common import page_ctx

router = APIRouter()

STATUS_ORDER = ["Interested", "Toured", "Considering", "Offer out", "Under contract", "Passed"]


OFFER_STATUSES = ["Draft", "Pending", "Countered", "Accepted", "Declined", "Withdrawn"]


def _templates(request: Request):
    return request.app.state.templates


def _int(s):
    s = (s or "").replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else None


def _float(s):
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _cents(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return int(round(float(s) * 100))
    except ValueError:
        return None


def _house_folder(h: House) -> PurePosixPath:
    return PurePosixPath("buy") / slugify(h.title)


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

    # Card image: the house's first uploaded photo, else the scraped listing image.
    heroes: dict[int, str] = {}
    for r in conn.execute(
        "SELECT iif.item_id, MIN(f.id) AS fid FROM item_files iif JOIN files f ON f.id = iif.file_id"
        " WHERE iif.role = 'photo' AND f.thumb_path IS NOT NULL GROUP BY iif.item_id"
    ):
        heroes[r["item_id"]] = f"/documents/thumb/{r['fid']}"
    for h in houses:
        if h.id not in heroes:
            link = next((l for l in h.other_links if l.get("label") == "Hero image"), None)
            if link and link.get("url", "").startswith("https://"):
                heroes[h.id] = link["url"]

    ctx = page_ctx(request, conn, who, active="Houses")
    ctx.update({
        "heroes": heroes,
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
        return RedirectResponse(url="/houses", status_code=302)

    notes = notes_repo.list_for(conn, house_id)
    note_photos: dict[int, list] = {}
    for r in conn.execute(
        "SELECT nf.note_id, f.id, f.original_name, f.thumb_path FROM note_files nf"
        " JOIN files f ON f.id = nf.file_id JOIN notes n ON n.id = nf.note_id"
        " WHERE n.item_id = ? ORDER BY f.id", (house_id,),
    ):
        note_photos.setdefault(r["note_id"], []).append(r)
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
        "note_photos": note_photos,
        "offer_statuses": OFFER_STATUSES,
        "offer_rows": offer_rows,
        "dates": dates,
        "people": people,
        "photos": photo_files,
        "files": doc_files,
        "facts": facts,
        "statuses": STATUS_ORDER,
    })
    return _templates(request).TemplateResponse(request, "house_detail.html", ctx)


# ---- house page actions ----

def _require_house(conn, house_id: int) -> House:
    h = items_repo.get_house(conn, house_id)
    if not h:
        raise HTTPException(status_code=404)
    return h


def _back(house_id: int) -> RedirectResponse:
    return RedirectResponse(url=f"/houses/{house_id}", status_code=303)


@router.post("/houses/{house_id}/status")
def set_status(
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    status: Annotated[str, Form()],
):
    h = _require_house(conn, house_id)
    if status in STATUS_ORDER and status != h.status:
        items_repo.update(conn, house_id, status=status)
        activity_repo.log(conn, actor=who, verb="status",
                          text=f"moved {h.title} to {status}", item_id=house_id)
    return _back(house_id)


@router.post("/houses/{house_id}/rating")
def set_rating(
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
    rating: Annotated[str, Form()] = "",
):
    h = _require_house(conn, house_id)
    ratings = dict(h.ratings)
    n = _int(rating)
    if n is not None and 1 <= n <= 5:
        ratings[who] = n
        activity_repo.log(conn, actor=who, verb="rated",
                          text=f"rated {h.title} {n}/5", item_id=house_id)
    else:
        ratings.pop(who, None)
    items_repo.update(conn, house_id, fields=dataclasses.replace(h, ratings=ratings).to_fields())
    return _back(house_id)


@router.post("/houses/{house_id}/edit")
async def edit_house(
    request: Request,
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
):
    h = _require_house(conn, house_id)
    form = await request.form()
    g = lambda k: (form.get(k) or "").strip()  # noqa: E731

    # Custom fields arrive as parallel ck/cv lists; blank keys drop the row.
    custom = {}
    for k, v in zip(form.getlist("ck"), form.getlist("cv")):
        if k.strip():
            custom[k.strip()] = v.strip()

    updated = dataclasses.replace(
        h,
        address=g("address"), listing_url=g("listing_url"),
        price_cents=_cents(g("price")), beds=_float(g("beds")), baths=_float(g("baths")),
        sqft=_int(g("sqft")), year_built=_int(g("year_built")), lot=g("lot"),
        garage=g("garage"), taxes_cents=_cents(g("taxes")), tour_date=g("tour_date"),
        best_thing=g("best_thing"), worst_thing=g("worst_thing"), custom=custom,
    )
    items_repo.update(conn, house_id, title=g("title") or h.title, fields=updated.to_fields())
    return _back(house_id)


@router.post("/houses/{house_id}/notes/new")
async def add_house_note(
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str, Depends(current_user)],
    body: Annotated[str, Form()] = "",
    photos: Annotated[list[UploadFile], File()] = (),
):
    h = _require_house(conn, house_id)
    uploads = [p for p in (photos or []) if p and p.filename]
    body = body.strip()
    if not body and not uploads:
        return _back(house_id)
    note_id = notes_repo.add(conn, item_id=house_id, author=who,
                             body_md=body or f"Added {len(uploads)} photo(s).")
    for p in uploads:
        try:
            fid = files_repo.save_upload(
                conn, cfg.files_root, _house_folder(h) / p.filename, p,
                uploaded_by=who, tags=["Photos"],
            )
        except files_repo.UploadTooLarge:
            raise HTTPException(status_code=413, detail=f"{p.filename} is over 50 MB")
        files_repo.link_to_item(conn, fid, house_id, role="photo")
        conn.execute("INSERT OR IGNORE INTO note_files(note_id, file_id) VALUES (?, ?)",
                     (note_id, fid))
    activity_repo.log(conn, actor=who, verb="added-note",
                      text=f"added a note to {h.title}", item_id=house_id)
    return _back(house_id)


@router.post("/houses/{house_id}/files")
async def attach_house_files(
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str, Depends(current_user)],
    files: Annotated[list[UploadFile], File()],
    tags: Annotated[str, Form()] = "",
):
    h = _require_house(conn, house_id)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    for f in files:
        if not f or not f.filename:
            continue
        try:
            fid = files_repo.save_upload(conn, cfg.files_root, _house_folder(h) / f.filename, f,
                                         uploaded_by=who, tags=tag_list)
        except files_repo.UploadTooLarge:
            raise HTTPException(status_code=413, detail=f"{f.filename} is over 50 MB")
        files_repo.link_to_item(conn, fid, house_id)
        activity_repo.log(conn, actor=who, verb="uploaded-file",
                          text=f"attached {f.filename} to {h.title}", item_id=house_id)
    return _back(house_id)


@router.post("/houses/{house_id}/offers/new")
async def add_offer(
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    cfg: Annotated[Config, Depends(get_config)],
    who: Annotated[str, Depends(current_user)],
    amount: Annotated[str, Form()],
    status: Annotated[str, Form()] = "Draft",
    sent_date: Annotated[str, Form()] = "",
    expires_at: Annotated[str, Form()] = "",
    contingencies: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile], File()] = (),
):
    h = _require_house(conn, house_id)
    cents = _cents(amount) or 0
    oid = offers_repo.add(
        conn, house_id=house_id, amount_cents=cents,
        sent_date=sent_date or None, expires_at=expires_at or None,
        status=status if status in OFFER_STATUSES else "Draft",
        contingencies=contingencies.strip(),
    )
    for f in files or []:
        if not f or not f.filename:
            continue
        try:
            fid = files_repo.save_upload(conn, cfg.files_root, _house_folder(h) / f.filename, f,
                                         uploaded_by=who, tags=["Offers"])
        except files_repo.UploadTooLarge:
            raise HTTPException(status_code=413, detail=f"{f.filename} is over 50 MB")
        files_repo.link_to_item(conn, fid, house_id, role="offer_doc")
        offers_repo.attach_file(conn, oid, fid)
    activity_repo.log(conn, actor=who, verb="offer",
                      text=f"logged a ${cents // 100:,} offer on {h.title}", item_id=house_id)
    return _back(house_id)


@router.post("/houses/{house_id}/offers/{offer_id}/status")
def set_offer_status(
    house_id: int,
    offer_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    status: Annotated[str, Form()],
):
    if status in OFFER_STATUSES:
        conn.execute("UPDATE offers SET status=? WHERE id=? AND house_id=?",
                     (status, offer_id, house_id))
    return _back(house_id)


@router.post("/houses/{house_id}/delete")
def delete_house(
    house_id: int,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    who: Annotated[str, Depends(current_user)],
):
    """Removes the house, its notes and offers. Uploaded files stay on disk and
    in Documents (unlinked) — deleting paperwork should be a separate decision."""
    h = _require_house(conn, house_id)
    conn.execute("DELETE FROM items WHERE id=?", (house_id,))
    activity_repo.log(conn, actor=who, verb="deleted", text=f"deleted house {h.title}")
    return RedirectResponse(url="/houses", status_code=303)


def _facts_for(h: House) -> list[dict[str, str]]:
    def dc(cents): return f"${(cents // 100):,}" if cents else "—"
    def num(v, suffix=""): return f"{v}{suffix}" if v is not None else "—"
    def bb():
        if h.beds is None and h.baths is None:
            return "—"
        b = f"{h.beds:g}" if h.beds is not None else "—"
        ba = f"{h.baths:g}" if h.baths is not None else "—"
        return f"{b} / {ba}"
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
