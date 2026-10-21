"""Only one quote per task can be chosen at a time.

Two layers enforce this:
  1. quotes_repo.choose() runs 'clear others, set this one' in a transaction.
  2. A partial unique index (quotes_one_chosen) is the DB-level backstop so
     any direct SQL that tries to set a second chosen row raises IntegrityError.

The tests exercise both layers.
"""
from __future__ import annotations

import pytest
import sqlite3

from app.repo import items as items_repo
from app.repo import quotes as quotes_repo


def _make_task(conn):
    return items_repo.insert(
        conn, type_="task", title="Refinish floors", status="Quoting",
        created_by="Stuart",
    )


def test_choose_flips_other_quotes_off(conn):
    task_id = _make_task(conn)
    a = quotes_repo.add(conn, task_id=task_id, vendor="A", amount_cents=100)
    b = quotes_repo.add(conn, task_id=task_id, vendor="B", amount_cents=200)
    c = quotes_repo.add(conn, task_id=task_id, vendor="C", amount_cents=300)

    quotes_repo.choose(conn, task_id=task_id, quote_id=b)
    chosen = conn.execute(
        "SELECT id FROM quotes WHERE task_id=? AND chosen=1", (task_id,)
    ).fetchall()
    assert [r[0] for r in chosen] == [b]

    quotes_repo.choose(conn, task_id=task_id, quote_id=c)
    chosen = conn.execute(
        "SELECT id FROM quotes WHERE task_id=? AND chosen=1", (task_id,)
    ).fetchall()
    assert [r[0] for r in chosen] == [c]


def test_add_with_chosen_true_clears_siblings(conn):
    task_id = _make_task(conn)
    a = quotes_repo.add(conn, task_id=task_id, vendor="A", amount_cents=100, chosen=True)
    b = quotes_repo.add(conn, task_id=task_id, vendor="B", amount_cents=200, chosen=True)
    chosen_ids = [r[0] for r in conn.execute(
        "SELECT id FROM quotes WHERE task_id=? AND chosen=1 ORDER BY id", (task_id,)
    ).fetchall()]
    assert chosen_ids == [b]


def test_db_level_backstop_rejects_two_chosen_per_task(conn):
    """Even if someone bypasses the repo and sets chosen=1 directly, the
    partial unique index refuses a second chosen row for the same task."""
    task_id = _make_task(conn)
    quotes_repo.add(conn, task_id=task_id, vendor="A", amount_cents=100, chosen=True)
    conn.execute(
        "INSERT INTO quotes(task_id, vendor, amount_cents, chosen) VALUES (?, ?, ?, 0)",
        (task_id, "B", 200),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE quotes SET chosen=1 WHERE task_id=? AND vendor='B'", (task_id,))


def test_different_tasks_can_each_have_one_chosen(conn):
    t1 = _make_task(conn)
    t2 = items_repo.insert(
        conn, type_="task", title="Paint", status="Quoting", created_by="Stuart",
    )
    quotes_repo.add(conn, task_id=t1, vendor="A", amount_cents=100, chosen=True)
    quotes_repo.add(conn, task_id=t2, vendor="B", amount_cents=200, chosen=True)
    n = conn.execute("SELECT COUNT(*) FROM quotes WHERE chosen=1").fetchone()[0]
    assert n == 2


def test_clear_choice(conn):
    task_id = _make_task(conn)
    quotes_repo.add(conn, task_id=task_id, vendor="A", amount_cents=100, chosen=True)
    quotes_repo.clear_choice(conn, task_id)
    chosen = conn.execute(
        "SELECT COUNT(*) FROM quotes WHERE task_id=? AND chosen=1", (task_id,)
    ).fetchone()[0]
    assert chosen == 0


def test_chosen_total_cents_sums_across_tasks(conn):
    t1 = _make_task(conn)
    t2 = items_repo.insert(
        conn, type_="task", title="Paint", status="Quoting", created_by="Stuart",
    )
    quotes_repo.add(conn, task_id=t1, vendor="A", amount_cents=290_000, chosen=True)
    quotes_repo.add(conn, task_id=t1, vendor="A2", amount_cents=340_000)  # not chosen
    quotes_repo.add(conn, task_id=t2, vendor="B", amount_cents=195_000, chosen=True)
    assert quotes_repo.chosen_total_cents(conn) == 290_000 + 195_000
