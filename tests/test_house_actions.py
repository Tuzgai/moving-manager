"""House page actions end to end through the app."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.config as cfg_mod
from app import db as db_mod
from app.main import app
from app.repo import items as items_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    real = cfg_mod.load()
    fake = cfg_mod.Config(
        host=real.host, port=real.port, data_dir=tmp_path / "data",
        files_root=tmp_path / "files", backup_dir=tmp_path / "b", backup_keep=14,
        users=real.users,
    )
    monkeypatch.setattr(cfg_mod, "load", lambda: fake)
    with TestClient(app) as c:
        c.cfg = fake
        yield c


def _house(client) -> int:
    conn = db_mod.connect(client.cfg.db_path)
    try:
        return items_repo.insert(conn, type_="house", title="Blue cape", status="Interested",
                                 created_by="Stuart", fields={"price_cents": 36_500_000})
    finally:
        conn.close()


def _get(client, hid):
    conn = db_mod.connect(client.cfg.db_path)
    try:
        return items_repo.get_house(conn, hid), conn.execute(
            "SELECT * FROM notes WHERE item_id=?", (hid,)).fetchall()
    finally:
        conn.close()


def test_status_rating_and_edit(client):
    hid = _house(client)
    client.cookies.set("who", "Ashley")
    assert client.post(f"/houses/{hid}/status", data={"status": "Toured"}).status_code in (200, 303)
    client.post(f"/houses/{hid}/rating", data={"rating": "4"})
    client.post(f"/houses/{hid}/edit", data={
        "title": "Blue cape", "price": "359,900", "beds": "3", "baths": "1.5",
        "ck": ["Radon test", ""], "cv": ["2.1 pCi/L", ""],
    })
    h, _ = _get(client, hid)
    assert h.status == "Toured"
    assert h.ratings == {"Ashley": 4}
    assert h.price_cents == 35_990_000
    assert h.baths == 1.5
    assert h.custom == {"Radon test": "2.1 pCi/L"}


def test_note_with_photo_links_photo_to_note(client):
    hid = _house(client)
    buf = io.BytesIO()
    Image.new("RGB", (600, 400), (10, 20, 30)).save(buf, "JPEG")
    buf.seek(0)
    client.post(f"/houses/{hid}/notes/new", data={"body": "**Roof** looks new"},
                files={"photos": ("roof.jpg", buf, "image/jpeg")})
    _, notes = _get(client, hid)
    assert len(notes) == 1
    conn = db_mod.connect(client.cfg.db_path)
    linked = conn.execute("SELECT COUNT(*) FROM note_files WHERE note_id=?", (notes[0]["id"],)).fetchone()[0]
    conn.close()
    assert linked == 1
    page = client.get(f"/houses/{hid}").text
    assert "<strong>Roof</strong>" in page
    assert "/documents/thumb/" in page


def test_offer_and_delete(client):
    hid = _house(client)
    client.post(f"/houses/{hid}/offers/new", data={"amount": "368000", "status": "Pending"},
                files={"files": ("pa.pdf", io.BytesIO(b"%PDF"), "application/pdf")})
    conn = db_mod.connect(client.cfg.db_path)
    offer = conn.execute("SELECT * FROM offers WHERE house_id=?", (hid,)).fetchone()
    docs = conn.execute("SELECT COUNT(*) FROM offer_files WHERE offer_id=?", (offer["id"],)).fetchone()[0]
    conn.close()
    assert offer["amount_cents"] == 36_800_000 and docs == 1

    client.post(f"/houses/{hid}/delete")
    h, notes = _get(client, hid)
    assert h is None
    conn = db_mod.connect(client.cfg.db_path)
    files_left = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    assert files_left == 1  # paperwork survives the house


def test_html_upload_served_as_download(client):
    r = client.post("/documents/upload", files={"files": ("page.html", io.BytesIO(b"<script>x</script>"), "text/html")})
    assert r.status_code in (200, 303)
    conn = db_mod.connect(client.cfg.db_path)
    fid = conn.execute("SELECT id FROM files").fetchone()[0]
    conn.close()
    r = client.get(f"/documents/file/{fid}")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
