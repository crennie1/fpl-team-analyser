"""SQLite helpers: connection, schema and SQL-file application."""
import sqlite3
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"
VIEW_FILES = ("forecast.sql", "squad.sql")


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn):
    """Add columns that older databases lack (CREATE TABLE IF NOT EXISTS keeps old tables)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(player_snapshot)")}
    if cols and "news" not in cols:
        conn.execute("ALTER TABLE player_snapshot ADD COLUMN news TEXT")


def apply_sql(conn, *files):
    """Run fpl/sql/<file> for each name, in order."""
    for name in files:
        conn.executescript((SQL_DIR / name).read_text())
        if name == "schema.sql":
            _migrate(conn)
    conn.commit()


def apply_views(conn):
    """Apply forecast.sql then squad.sql, skipping files that do not exist yet."""
    present = [f for f in VIEW_FILES if (SQL_DIR / f).exists()]
    if present:
        apply_sql(conn, *present)


def memory_copy(path):
    """Copy the database at `path` into memory and (re)create the views."""
    src = sqlite3.connect(str(path))
    try:
        mem = sqlite3.connect(":memory:")
        src.backup(mem)
    finally:
        src.close()
    mem.row_factory = sqlite3.Row
    mem.execute("PRAGMA foreign_keys = ON")
    apply_views(mem)
    return mem
