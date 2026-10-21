"""Tag counting, listing filters, thumbnails."""
from __future__ import annotations

import io
import json
from pathlib import Path, PurePosixPath

from PIL import Image

from app.repo import files as files_repo


def _add_file(conn, name, tags, uploaded_by="Stuart", stored_path=None):
    return files_repo.insert(
        conn,
        original_name=name,
        stored_path=stored_path or f"test/{name}",
        size_bytes=100,
        mime_type=files_repo.guess_mime(name),
        tags=json.dumps(tags),
        uploaded_by=uploaded_by,
    )


def test_tag_counts_fans_out_json_arrays(conn):
    _add_file(conn, "a.pdf", ["Offers", "Mortgage"])
    _add_file(conn, "b.pdf", ["Offers"])
    _add_file(conn, "c.pdf", ["Quotes"])
    _add_file(conn, "d.pdf", [])
    counts = files_repo.tag_counts(conn)
    assert counts == {"Offers": 2, "Mortgage": 1, "Quotes": 1}


def test_list_all_filters_by_tag_exact(conn):
    _add_file(conn, "a.pdf", ["Quotes"])
    _add_file(conn, "b.pdf", ["QuotesExtra"])
    rows = files_repo.list_all(conn, tag="Quotes")
    names = sorted(r["original_name"] for r in rows)
    assert names == ["a.pdf"]  # the quoted token form prevents false matches


def test_list_all_search_matches_name_or_tag(conn):
    _add_file(conn, "mortgage-statement.pdf", ["Mortgage"])
    _add_file(conn, "random.pdf", ["Offers"])
    rows = files_repo.list_all(conn, q="mortgage")
    names = sorted(r["original_name"] for r in rows)
    assert names == ["mortgage-statement.pdf"]


def test_linked_items_groups_by_file(conn):
    from app.repo import items as items_repo
    fid1 = _add_file(conn, "a.pdf", [])
    fid2 = _add_file(conn, "b.pdf", [])
    h = items_repo.insert(conn, type_="house", title="Blue cape", status="Toured", created_by="Stuart")
    t = items_repo.insert(conn, type_="task", title="Paint", status="Not started", created_by="Stuart")
    files_repo.link_to_item(conn, fid1, h)
    files_repo.link_to_item(conn, fid1, t)
    files_repo.link_to_item(conn, fid2, h)
    out = files_repo.linked_items(conn, [fid1, fid2])
    assert sorted(r["title"] for r in out[fid1]) == ["Blue cape", "Paint"]
    assert [r["title"] for r in out[fid2]] == ["Blue cape"]


def test_make_thumbnail_scales_to_long_edge(tmp_path: Path):
    # 1200x800 solid-color PNG -> expect a .thumb.jpg at 400x266 (approx)
    rel = PurePosixPath("buy/blue-cape/front.png")
    (tmp_path / rel.parent).mkdir(parents=True)
    img = Image.new("RGB", (1200, 800), color=(90, 110, 140))
    img.save(tmp_path / rel, "PNG")

    thumb_rel = files_repo.make_thumbnail(tmp_path, rel)
    assert str(thumb_rel) == "buy/blue-cape/front.thumb.jpg"

    with Image.open(tmp_path / thumb_rel) as t:
        assert max(t.size) == 400
        # Ratio preserved within rounding (Pillow uses integer dims)
        assert t.size == (400, 266) or t.size == (400, 267)


def test_make_thumbnail_returns_none_for_non_image(tmp_path: Path):
    rel = PurePosixPath("x.pdf")
    (tmp_path / rel).write_bytes(b"%PDF not really")
    assert files_repo.make_thumbnail(tmp_path, rel) is None


def test_is_image_detects_common_types():
    assert files_repo.is_image("image/jpeg")
    assert files_repo.is_image("image/png")
    assert not files_repo.is_image("application/pdf")
