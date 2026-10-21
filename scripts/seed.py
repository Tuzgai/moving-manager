"""Seed script: loads the mockup sample data into an empty DB.

Run with:
    uv run python scripts/seed.py           # refuses if the DB has any data
    uv run python scripts/seed.py --force   # wipes everything first

Data comes straight from the mockups' renderVals() scripts, with [Partner] -> Ashley.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as app_config
from app import db
from app.repo import activity as activity_repo
from app.repo import contacts as contacts_repo
from app.repo import items as items_repo
from app.repo import key_dates as key_dates_repo
from app.repo import notes as notes_repo
from app.repo import offers as offers_repo
from app.repo import quotes as quotes_repo


def wipe(conn):
    # Delete in FK order; schema_migrations stays so we don't re-migrate.
    for t in [
        "note_files", "item_files", "offer_files", "item_contacts",
        "quotes", "offers", "key_dates", "activity", "notes",
        "files", "contacts", "items",
    ]:
        conn.execute(f"DELETE FROM {t}")
    # Also wipe FTS (triggers won't catch bulk deletes if the table was empty)
    conn.execute("DELETE FROM search_index")


def seed(conn):
    wipe(conn)

    # --- Houses ---
    houses_data = [
        dict(title="Blue cape", status="Offer out",
             address="123 Elm St, Richfield, MN",
             listing_url="https://www.zillow.com/example-blue-cape",
             price_cents=36_500_000, beds=3, baths=2, sqft=1640, year_built=1948,
             lot="0.18 ac", garage="2-car det.", taxes_cents=421_000,
             tour_date="Oct 12", best_thing="Kitchen redone 2022",
             worst_thing="Small 2nd bath",
             ratings={"Stuart": 4, "Ashley": 4},
             other_links=[{"label": "MLS sheet", "url": "https://example.com/mls"}]),
        dict(title="Corner rambler", status="Considering",
             address="456 Oak Ln, Richfield, MN", listing_url="",
             price_cents=34_200_000, beds=3, baths=1.5, sqft=1380, year_built=1955,
             garage="1-car attached", lot="0.14 ac", taxes_cents=388_000,
             tour_date="Oct 19", best_thing="Walk to park",
             worst_thing="Tiny backyard",
             ratings={"Stuart": 4, "Ashley": 3}),
        dict(title="Brick bungalow", status="Interested",
             address="789 Maple Ave, Richfield, MN", listing_url="",
             price_cents=38_900_000, beds=4, baths=2, sqft=1820, year_built=1942,
             garage="2-car detached", lot="0.22 ac", taxes_cents=452_000,
             best_thing="Big lot", worst_thing="Original windows",
             ratings={}),
        dict(title="Split-level w/ deck", status="Toured",
             address="321 Pine Rd, Richfield, MN", listing_url="",
             price_cents=35_500_000, beds=3, baths=2, sqft=1710, year_built=1968,
             garage="2-car tuck-under", lot="0.19 ac", taxes_cents=410_000,
             tour_date="Oct 5", best_thing="Deck + yard",
             worst_thing="Dark lower level",
             ratings={"Stuart": 3, "Ashley": 3}),
        dict(title="Tudor near park", status="Passed",
             address="654 Birch St, Richfield, MN", listing_url="",
             price_cents=41_000_000, beds=3, baths=2, sqft=1690, year_built=1932,
             garage="1-car", lot="0.16 ac", tour_date="Sep 28",
             ratings={"Stuart": 2, "Ashley": 3}),
        dict(title="Lakeside ranch", status="Interested",
             address="987 Lake Dr, Richfield, MN", listing_url="",
             price_cents=37_800_000, beds=3, baths=2, sqft=1550,
             ratings={}),
    ]

    house_ids: dict[str, int] = {}
    for h in houses_data:
        hid = items_repo.insert(
            conn, type_="house", title=h["title"], status=h["status"],
            created_by="Stuart", tags=["buy"], fields={k: v for k, v in h.items() if k not in ("title", "status")},
        )
        house_ids[h["title"]] = hid

    # Notes on Blue cape
    blue = house_ids["Blue cape"]
    notes_repo.add(conn, item_id=blue, author="Ashley", body_md=(
        "Drove by at night — street is quiet, decent lighting.\n"
        "Neighbor said the sewer line was replaced 2020; ask for proof."
    ), created_at="2026-10-19 21:14:00")
    notes_repo.add(conn, item_id=blue, author="Stuart", body_md=(
        "Kitchen redone 2022, nice. Second bath is tight.\n"
        "Basement dry, some efflorescence on north wall."
    ), created_at="2026-10-12 15:40:00")
    notes_repo.add(conn, item_id=blue, author="Stuart",
                   body_md="Roof looks newer than listing says. Furnace 2011.",
                   created_at="2026-10-12 14:05:00")

    # One note on the corner rambler (shows in dashboard activity)
    cr = house_ids["Corner rambler"]
    notes_repo.add(conn, item_id=cr, author="Ashley",
                   body_md="Backyard smaller than photos.",
                   created_at="2026-10-21 07:52:00")

    # --- Offers ---
    offer_id = offers_repo.add(
        conn, house_id=blue, amount_cents=36_800_000,
        sent_date="2026-10-20", expires_at="2026-10-22",
        status="Pending", contingencies="inspection + financing contingent",
    )

    # --- Tasks (selling) ---
    tasks_data = [
        dict(title="Refinish living room floors", status="Quoting",
             fields=dict(area="Living room", priority="High", assignee="Stuart", due_date="2027-02-15")),
        dict(title="Roof inspection + minor repair", status="Waiting",
             fields=dict(area="Exterior", priority="Med", assignee="Both", due_date="2026-11-30")),
        dict(title="Patch + paint hallway", status="Doing it ourselves",
             fields=dict(area="Hallway", priority="High", assignee="Both", due_date="2026-11-08")),
        dict(title="Get 3rd floor-refinish quote", status="Not started",
             fields=dict(area="Living room", priority="High", assignee="Stuart", due_date="2026-11-01")),
        dict(title="Replace garage door seal", status="Not started",
             fields=dict(area="Garage", priority="Low", assignee="Stuart", due_date="2026-12-01")),
        dict(title="Declutter basement storage", status="Not started",
             fields=dict(area="Basement", priority="Med", assignee="Both", due_date="2027-01-15")),
    ]
    task_ids = {}
    for t in tasks_data:
        tid = items_repo.insert(
            conn, type_="task", title=t["title"], status=t["status"],
            created_by="Stuart", tags=["sell"], fields=t["fields"],
        )
        task_ids[t["title"]] = tid

    # Quotes
    floors = task_ids["Refinish living room floors"]
    quotes_repo.add(conn, task_id=floors, vendor="Vendor A",
                    amount_cents=340_000, received_date="2026-10-09",
                    expires_at="2026-12-09", note="Sand + 2 coats, 3 days")
    quotes_repo.add(conn, task_id=floors, vendor="Vendor B",
                    amount_cents=290_000, received_date="2026-10-20",
                    expires_at="2026-11-03",
                    note="Sand + 3 coats, 4 days, moves furniture", chosen=True)

    roof = task_ids["Roof inspection + minor repair"]
    quotes_repo.add(conn, task_id=roof, vendor="Vendor C",
                    amount_cents=25_000, received_date="2026-10-15",
                    note="Inspection only")

    paint = task_ids["Patch + paint hallway"]
    quotes_repo.add(conn, task_id=paint, vendor="DIY materials",
                    amount_cents=195_000, received_date="2026-10-18",
                    note="Paint, spackle, rollers", chosen=True)

    notes_repo.add(conn, item_id=floors, author="Stuart", body_md=(
        "B is cheaper but quote expires fast. Want a third bid before deciding."
    ), created_at="2026-10-20 09:00:00")
    notes_repo.add(conn, item_id=roof, author="Ashley",
                   body_md="Called C, waiting on repair estimate after inspection.",
                   created_at="2026-10-15 10:30:00")

    # --- Contacts ---
    la = contacts_repo.add(conn, name="Jamie Patel", role="Seller's agent",
                           phone="612-555-0101", email="jamie@realty.example",
                           notes="Blue cape listing agent")
    ba = contacts_repo.add(conn, name="Taylor Chen", role="Buyer's agent (ours)",
                           phone="612-555-0138", email="taylor@realty.example")
    insp = contacts_repo.add(conn, name="Northstar Inspections", role="Home inspector",
                             phone="612-555-0177")
    contacts_repo.link(conn, blue, la)
    contacts_repo.link(conn, blue, ba)

    # --- Key dates ---
    kd = key_dates_repo.add
    kd(conn, title="Tour: Brick bungalow", on_date="2026-10-24", category="buy",
       sub="2:00 pm with listing agent", item_id=house_ids["Brick bungalow"])
    kd(conn, title="Offer response deadline", on_date="2026-10-22", category="buy",
       sub="Blue cape", item_id=blue)
    kd(conn, title="Floor refinish quote expires", on_date="2026-11-03", category="sell",
       sub="Vendor B · $2,900", item_id=floors)
    kd(conn, title="Pre-listing inspection", on_date="2026-11-15", category="sell",
       sub="Inspector booked, 3 hrs")
    kd(conn, title="Mortgage pre-approval renewal", on_date="2027-01-10", category="buy",
       sub="Lender needs updated pay stubs")
    kd(conn, title="Listing photos", on_date="2027-03-02", category="sell",
       sub="All staging tasks done by here")
    kd(conn, title="Target list date", on_date="2027-04-01", category="sell",
       sub="On the market by here")
    kd(conn, title="Target close", on_date="2026-12-15", category="buy", item_id=blue)

    # --- Activity feed ---
    log = activity_repo.log
    log(conn, actor="Ashley",
        text="added a note to Corner rambler: “Backyard smaller than photos.”",
        verb="added-note", item_id=cr, created_at="2026-10-21 07:52:00")
    log(conn, actor="Stuart",
        text="attached a quote (Vendor B, $2,900) to Refinish floors",
        verb="added-quote", item_id=floors, created_at="2026-10-20 18:10:00")
    log(conn, actor="Ashley", text="rated Blue cape 4/5",
        verb="rated", item_id=blue, created_at="2026-10-19 10:00:00")
    log(conn, actor="Stuart", text="uploaded Current mortgage statement (PDF)",
        verb="uploaded-file", created_at="2026-10-18 12:00:00")

    # Seed timestamps above are written as local wall-clock times; the app
    # stores UTC (SQLite datetime('now')). The 'utc' modifier converts.
    conn.execute("UPDATE notes SET created_at = datetime(created_at, 'utc')")
    conn.execute("UPDATE activity SET created_at = datetime(created_at, 'utc')")

    print(f"Seeded: {len(houses_data)} houses, {len(tasks_data)} tasks, "
          f"{conn.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]} quotes, "
          f"{conn.execute('SELECT COUNT(*) FROM notes').fetchone()[0]} notes.")


def has_data(conn) -> bool:
    return any(
        conn.execute(f"SELECT EXISTS(SELECT 1 FROM {t})").fetchone()[0]
        for t in ("items", "files", "contacts", "key_dates")
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Load the mockup sample data.")
    p.add_argument("--force", action="store_true",
                   help="wipe an existing database first (destroys real data)")
    args = p.parse_args(argv)

    cfg = app_config.load()
    conn = db.init(cfg.db_path)
    try:
        if has_data(conn) and not args.force:
            print(f"{cfg.db_path} already has data; refusing to wipe it. "
                  "Re-run with --force if you really want the sample data instead.")
            return 1
        seed(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
