"""Listing scraper. All tests pass fixture HTML — no network."""
from __future__ import annotations

from app import scrape


JSONLD_PAGE = """
<html><head>
<meta property="og:title" content="123 Elm St, Richfield, MN 55423 | Zillow">
<meta property="og:image" content="https://photos.zillow.com/example.jpg">
<meta property="og:description" content="Lovely Cape Cod with updated kitchen">
<script type="application/ld+json">
{"@type":"SingleFamilyResidence","name":"123 Elm St","description":"Cape Cod",
 "address":{"streetAddress":"123 Elm St","addressLocality":"Richfield","addressRegion":"MN","postalCode":"55423"},
 "numberOfBedrooms":3,"numberOfBathroomsTotal":2,
 "floorSize":{"@type":"QuantitativeValue","value":"1640"},
 "offers":{"@type":"Offer","price":"365000"}}
</script>
</head><body>$365,000 · 3 bd · 2 ba · 1,640 sqft · built 1948</body></html>
"""


def test_scrape_prefers_json_ld():
    r = scrape.scrape("http://example.test/", html_text=JSONLD_PAGE)
    assert r.source == "json-ld"
    assert r.title == "123 Elm St"
    assert r.address == "123 Elm St, Richfield, MN, 55423"
    assert r.beds == 3
    assert r.baths == 2
    assert r.sqft == 1640
    assert r.price_cents == 36_500_000
    assert r.image_url == "https://photos.zillow.com/example.jpg"


OG_ONLY = """
<html><head>
<meta property="og:title" content="789 Maple Ave · Redfin">
<meta property="og:image" content="https://ssl.cdn-redfin.com/x.jpg">
<meta property="og:description" content="4bd / 2ba brick bungalow in Richfield">
</head><body>
<div>$389,000 · 4 beds · 2 baths · 1,820 sq ft · Built 1942</div>
</body></html>
"""


def test_scrape_fills_from_og_then_regex():
    r = scrape.scrape("http://example.test/", html_text=OG_ONLY)
    # og provided the title; regex fallback filled numbers
    assert r.title.startswith("789 Maple Ave")
    assert r.image_url.endswith("x.jpg")
    assert r.price_cents == 38_900_000
    assert r.beds == 4
    assert r.baths == 2
    assert r.sqft == 1820
    assert r.year_built == 1942
    # Source is reported as whatever the strongest signal was
    assert r.source in ("open-graph", "regex")


ZILLOW_STYLE = """
<script type="application/ld+json">
{"@type":["RealEstateListing","Product"],"name":"8810 Van Buren St NE, Blaine, MN 55434",
 "offers":{"price":"294600"}}
</script>
"""


def test_address_named_listing_backfills_address_and_shortens_nickname():
    r = scrape.scrape("http://example.test/", html_text=ZILLOW_STYLE)
    assert r.address == "8810 Van Buren St NE, Blaine, MN 55434"
    assert r.title == "8810 Van Buren St NE"
    assert r.price_cents == 29_460_000


def test_scrape_returns_empty_on_fetch_failure(monkeypatch):
    monkeypatch.setattr(scrape, "fetch", lambda url: None)
    r = scrape.scrape("http://unreachable.test/")
    assert not r.fetched
    assert r.title == ""
    assert r.source == "none"


def test_nickname_from_title_strips_realtor_tails():
    assert scrape.nickname_from_title("Blue cape — Zillow") == "Blue cape"
    assert scrape.nickname_from_title("Something Lovely | Redfin") == "Something Lovely"


def test_nickname_from_title_keeps_street_address():
    assert scrape.nickname_from_title("123 Elm St, Richfield, MN") == "123 Elm St"


def test_nickname_from_title_empty_falls_back():
    assert scrape.nickname_from_title("") == "New house"
