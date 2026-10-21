"""Shaped views over the generic `items` table.

These aren't an ORM; they're the shape returned by repo functions so routes and
templates aren't digging into JSON pouches directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Item:
    id: int
    type: str
    title: str
    status: str
    tags: list[str]
    fields: dict[str, Any]
    created_by: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row) -> "Item":
        return cls(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            status=row["status"],
            tags=json.loads(row["tags"]),
            fields=json.loads(row["fields"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class House:
    """A view over an `items` row of type='house'. Fields unpack the JSON pouch."""
    id: int
    title: str                  # "nickname" in the mockups
    status: str
    tags: list[str]
    address: str = ""
    listing_url: str = ""
    other_links: list[dict[str, str]] = field(default_factory=list)
    price_cents: int | None = None
    beds: float | None = None
    baths: float | None = None
    sqft: int | None = None
    year_built: int | None = None
    lot: str = ""
    garage: str = ""
    taxes_cents: int | None = None
    tour_date: str = ""
    best_thing: str = ""
    worst_thing: str = ""
    ratings: dict[str, int] = field(default_factory=dict)  # {"Stuart": 4, "Ashley": 4}
    custom: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    _KNOWN = {
        "address", "listing_url", "other_links", "price_cents", "beds", "baths",
        "sqft", "year_built", "lot", "garage", "taxes_cents", "tour_date",
        "best_thing", "worst_thing", "ratings",
    }

    @classmethod
    def from_item(cls, it: Item) -> "House":
        f = it.fields
        known = {k: f.get(k) for k in cls._KNOWN if k in f}
        custom = {k: v for k, v in f.items() if k not in cls._KNOWN}
        # Normalize defaults
        known.setdefault("other_links", [])
        known.setdefault("ratings", {})
        return cls(
            id=it.id, title=it.title, status=it.status, tags=it.tags,
            created_by=it.created_by, created_at=it.created_at, updated_at=it.updated_at,
            custom=custom, **known,
        )

    def to_fields(self) -> dict[str, Any]:
        """Pack back into the JSON pouch (for inserts/updates)."""
        out: dict[str, Any] = {}
        for k in self._KNOWN:
            v = getattr(self, k)
            if v in (None, "", [], {}):
                continue
            out[k] = v
        out.update(self.custom)
        return out


@dataclass
class Task:
    id: int
    title: str
    status: str
    tags: list[str]
    area: str = ""
    priority: str = ""         # 'High' | 'Med' | 'Low'
    assignee: str = ""         # user name or 'Both'
    due_date: str = ""
    custom: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    _KNOWN = {"area", "priority", "assignee", "due_date"}

    @classmethod
    def from_item(cls, it: Item) -> "Task":
        f = it.fields
        known = {k: f.get(k, "") for k in cls._KNOWN}
        custom = {k: v for k, v in f.items() if k not in cls._KNOWN}
        return cls(
            id=it.id, title=it.title, status=it.status, tags=it.tags,
            created_by=it.created_by, created_at=it.created_at, updated_at=it.updated_at,
            custom=custom, **known,
        )
