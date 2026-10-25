"""Errors come back as readable pages or toasts, never JSON."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

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
    with TestClient(app, follow_redirects=False) as c:
        conn = db_mod.connect(fake.db_path)
        c.task_id = items_repo.insert(conn, type_="task", title="Paint", status="Not started",
                                      created_by="Stuart")
        c.house_id = items_repo.insert(conn, type_="house", title="Blue cape",
                                       status="Interested", created_by="Stuart")
        conn.close()
        yield c


def _error_param(resp) -> str:
    assert resp.status_code == 303
    loc = urlsplit(resp.headers["location"])
    assert not loc.scheme and not loc.netloc  # stays on this site
    return parse_qs(loc.query)["error"][0]


def test_missing_form_field_redirects_back_with_message(client):
    r = client.post("/tasks/tasks/new", data={"area": "x"},
                    headers={"referer": "http://hub.test/tasks?task=1&error=old"})
    msg = _error_param(r)
    assert msg == "Please add a title."
    assert urlsplit(r.headers["location"]).path == "/tasks"
    assert parse_qs(urlsplit(r.headers["location"]).query)["task"] == ["1"]


def test_bad_quote_amount_is_a_message_not_a_500(client):
    r = client.post(f"/tasks/{client.task_id}/quotes/new", data={"vendor": "V", "amount": "abc"},
                    headers={"referer": f"http://hub.test/tasks?task={client.task_id}"})
    assert "needs to be a number" in _error_param(r)


def test_upload_without_file_asks_for_one(client):
    r = client.post(f"/houses/{client.house_id}/files", data={"tags": "x"},
                    headers={"referer": f"http://hub.test/houses/{client.house_id}"})
    assert "at least one file" in _error_param(r)


def test_referer_host_is_ignored(client):
    r = client.post("/tasks/tasks/new", data={},
                    headers={"referer": "https://evil.example/phish?x=1"})
    assert r.headers["location"].startswith("/phish?")  # path only, never another host


def test_bad_page_url_renders_html_error_page(client):
    for url in ("/houses/abc", "/houses/99999/edit-does-not-exist", "/nope"):
        r = client.get(url)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")
        assert "Something's not right" in r.text


def test_htmx_error_is_plain_text(client):
    r = client.post("/tasks/abc/complete", headers={"hx-request": "true"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/plain")
    assert "{" not in r.text
