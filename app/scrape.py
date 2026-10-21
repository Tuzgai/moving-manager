"""Best-effort listing scraper.

The goal is to pre-fill a house from a Zillow/Redfin/MLS URL so the user
doesn't retype title/price/beds/baths. We fetch with a browser-ish UA and
pull three sources of truth in order of reliability:

  1. JSON-LD `<script type="application/ld+json">` blocks — well-defined
     Residence / Product schemas. These are the most reliable when present.
  2. Open Graph tags — og:title, og:description, og:image.
  3. Regex fallbacks for "beds", "baths", "sqft", "$price" in page text.

Sites block scrapers aggressively, so this is best-effort. If we get a 403
or empty result we return just the URL and let the user fill the rest.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
TIMEOUT = 10.0  # seconds
MAX_BYTES = 2 * 1024 * 1024  # 2 MB cap on scraped HTML


@dataclass
class ScrapedListing:
    url: str
    title: str = ""
    description: str = ""
    image_url: str = ""
    address: str = ""
    price_cents: int | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None
    year_built: int | None = None
    source: str = "none"      # 'json-ld' | 'open-graph' | 'regex' | 'none'
    fetched: bool = False


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            # Anything but 200 (e.g. Redfin's 202 bot challenge) means no listing content.
            if resp.status != 200:
                return None
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raw = raw[:MAX_BYTES]
            body = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
            return body or None
    except Exception:
        return None


# --- parsers ---

OG_RE = re.compile(
    r'<meta\s+[^>]*?property=["\'](og:[a-z:_]+)["\'][^>]*?content=["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL,
)
OG_RE_ALT = re.compile(  # content before property
    r'<meta\s+[^>]*?content=["\']([^"\']+)["\'][^>]*?property=["\'](og:[a-z:_]+)["\']',
    re.IGNORECASE | re.DOTALL,
)
JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _open_graph(html_text: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for m in OG_RE.finditer(html_text):
        tags.setdefault(m.group(1).lower(), html.unescape(m.group(2)))
    for m in OG_RE_ALT.finditer(html_text):
        tags.setdefault(m.group(2).lower(), html.unescape(m.group(1)))
    return tags


def _json_ld(html_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in JSONLD_RE.finditer(html_text):
        body = m.group(1).strip()
        try:
            data = json.loads(body)
        except Exception:
            continue
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            # Common pattern: {"@graph": [...]}
            if isinstance(data.get("@graph"), list):
                out.extend(x for x in data["@graph"] if isinstance(x, dict))
            else:
                out.append(data)
    return out


def _pull_from_json_ld(blocks: list[dict[str, Any]], out: ScrapedListing) -> bool:
    """Fill out from JSON-LD if any block looks like a listing. Returns True if used."""
    used = False
    for b in blocks:
        t = b.get("@type")
        t_norm = (t if isinstance(t, str) else (t[0] if isinstance(t, list) and t else "")).lower()
        if "residence" in t_norm or t_norm in {"singlefamilyresidence", "house", "apartment",
                                                "product", "realestatelisting"}:
            used = True
            name = b.get("name")
            if isinstance(name, str) and not out.title:
                out.title = name.strip()
            desc = b.get("description")
            if isinstance(desc, str) and not out.description:
                out.description = desc.strip()
            addr = b.get("address")
            if isinstance(addr, dict):
                parts = [addr.get(k, "") for k in ("streetAddress", "addressLocality",
                                                   "addressRegion", "postalCode")]
                joined = ", ".join(p for p in parts if p)
                if joined and not out.address:
                    out.address = joined
            elif isinstance(addr, str) and not out.address:
                out.address = addr
            # Offers / price
            offers = b.get("offers")
            if isinstance(offers, dict):
                p = offers.get("price") or offers.get("lowPrice")
                if p is not None and out.price_cents is None:
                    try:
                        out.price_cents = int(round(float(p) * 100))
                    except (TypeError, ValueError):
                        pass
            if "numberOfRooms" in b and out.beds is None:
                try: out.beds = float(b["numberOfRooms"])
                except (TypeError, ValueError): pass
            if "numberOfBedrooms" in b and out.beds is None:
                try: out.beds = float(b["numberOfBedrooms"])
                except (TypeError, ValueError): pass
            if "numberOfBathroomsTotal" in b and out.baths is None:
                try: out.baths = float(b["numberOfBathroomsTotal"])
                except (TypeError, ValueError): pass
            if "floorSize" in b and out.sqft is None:
                fs = b["floorSize"]
                if isinstance(fs, dict):
                    v = fs.get("value")
                    try:
                        out.sqft = int(round(float(v)))
                    except (TypeError, ValueError):
                        pass
    return used


# Order matters: more specific first so "2.5 bath" doesn't swallow "bathrooms".
PRICE_RE = re.compile(r"\$([0-9]{1,3}(?:,[0-9]{3})+)(?!\d)")
BEDS_RE = re.compile(r"\b([0-9]+(?:\.5)?)\s*(?:beds?|br|bd|bedrooms?)\b", re.IGNORECASE)
BATHS_RE = re.compile(r"\b([0-9]+(?:\.[0-9])?)\s*(?:baths?|ba|bathrooms?)\b", re.IGNORECASE)
SQFT_RE = re.compile(r"\b([0-9][0-9,]{2,})\s*(?:sq\.?\s*ft|sqft|square\s*feet)\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:built\s*(?:in\s*)?|year\s*built[:\s]*)(1[89][0-9]{2}|20[0-9]{2})\b", re.IGNORECASE)


def _pull_from_regex(text: str, out: ScrapedListing) -> bool:
    """Last-resort scrape of the visible text. Marks source as 'regex' if it fills anything."""
    used = False
    if out.price_cents is None:
        m = PRICE_RE.search(text)
        if m:
            try:
                out.price_cents = int(round(float(m.group(1).replace(",", "")) * 100)); used = True
            except ValueError:
                pass
    if out.beds is None:
        m = BEDS_RE.search(text)
        if m:
            try: out.beds = float(m.group(1)); used = True
            except ValueError: pass
    if out.baths is None:
        m = BATHS_RE.search(text)
        if m:
            try: out.baths = float(m.group(1)); used = True
            except ValueError: pass
    if out.sqft is None:
        m = SQFT_RE.search(text)
        if m:
            try: out.sqft = int(m.group(1).replace(",", "")); used = True
            except ValueError: pass
    if out.year_built is None:
        m = YEAR_RE.search(text)
        if m:
            try: out.year_built = int(m.group(1)); used = True
            except ValueError: pass
    return used


US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
    "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}


def address_from_url(url: str) -> str:
    """Pull the street address out of a Redfin or Zillow listing URL slug.
    Redfin: /MN/Blaine/8828-Van-Buren-St-NE-55434/home/50985826
    Zillow: /homedetails/8810-Van-Buren-St-NE-Blaine-MN-55434/1548734_zpid/"""
    path = urllib.parse.urlparse(url).path
    m = re.search(r"/([A-Z]{2})/([^/]+)/(\d[^/]*?)-(\d{5})/home/", path)
    if m and m.group(1) in US_STATES:
        state, city, street, zipcode = m.groups()
        return f"{street.replace('-', ' ')}, {city.replace('-', ' ')}, {state} {zipcode}"
    m = re.search(r"/homedetails/(\d[^/]*?)-([A-Z]{2})-(\d{5})/", path)
    if m and m.group(2) in US_STATES:
        # Street and city run together in Zillow slugs; keep them as one chunk.
        return f"{m.group(1).replace('-', ' ')}, {m.group(2)} {m.group(3)}"
    return ""


def scrape(url: str, html_text: str | None = None) -> ScrapedListing:
    """Scrape a listing. Pass html_text to skip the HTTP fetch (used by tests)."""
    out = ScrapedListing(url=url)
    body = html_text if html_text is not None else fetch(url)
    if body is None:
        # Blocked or unreachable: the URL slug may still give us the address.
        addr = address_from_url(url)
        if addr:
            out.address = addr
            out.title = addr.split(",")[0]
            out.source = "url"
        return out
    out.fetched = True

    # 1. JSON-LD
    jsonld = _json_ld(body)
    jsonld_used = _pull_from_json_ld(jsonld, out)

    # 2. Open Graph (fills gaps)
    og = _open_graph(body)
    if og.get("og:title") and not out.title:
        out.title = og["og:title"].strip()
    if og.get("og:description") and not out.description:
        out.description = og["og:description"].strip()
    if og.get("og:image") and not out.image_url:
        out.image_url = og["og:image"].strip()
    og_used = any(v for v in og.values())

    # 3. Regex fallbacks over the raw body (we don't strip tags; attribute
    #    text often holds "3 beds · 2 baths · 1,640 sqft" verbatim)
    regex_used = _pull_from_regex(body, out)

    # Zillow-style listings name themselves by full address but omit the
    # address object; use the name as the address and shorten the nickname.
    if out.title and re.match(r"^\d+\s+\S+.*,", out.title):
        if not out.address:
            out.address = re.split(r"\s*[|·—]\s*", out.title, maxsplit=1)[0].strip()
        out.title = nickname_from_title(out.title)

    if jsonld_used:
        out.source = "json-ld"
    elif og_used:
        out.source = "open-graph"
    elif regex_used:
        out.source = "regex"
    else:
        out.source = "none"
    return out


def nickname_from_title(title: str) -> str:
    """Shorten an og:title to a usable nickname. Strip trailing "| Zillow" etc."""
    if not title:
        return "New house"
    cleaned = re.split(r"\s*[|·—-]\s*(?:zillow|redfin|realtor|homes?\.com|mls).*", title,
                       maxsplit=1, flags=re.IGNORECASE)[0]
    # Strip trailing commas / cities if the title is "123 Main St, Anywhere, MN 55423"
    first_part = cleaned.split(",")[0].strip()
    # If it's clearly a street address, keep that as the nickname
    if re.match(r"^\d+\s+\S+", first_part):
        return first_part
    return cleaned.strip() or "New house"
