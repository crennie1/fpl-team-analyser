"""Every statement in analysis/starter_queries.sql must run on the real database
and return at least one row. Read-only: the database is never changed."""
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "analysis" / "starter_queries.sql"
DB = ROOT / "data" / "fpl.db"


def split_statements(text):
    """Split the file into complete statements (comment-only chunks are dropped)."""
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if any(l.strip() and not l.strip().startswith("--") for l in buf.splitlines()):
                out.append(buf.strip())
            buf = ""
    return out


def test_file_has_three_worked_queries():
    assert len(split_statements(QUERIES.read_text())) == 3


@pytest.mark.parametrize("n", [0, 1, 2])
def test_query_returns_rows(n):
    sql = split_statements(QUERIES.read_text())[n]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 1
