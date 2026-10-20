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
    """Add columns that older databases lack (CREATE TABLE IF NOT EXISTS keeps old tables).

    Missing v2 tables are created by schema.sql itself (CREATE TABLE IF NOT EXISTS).
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(player_snapshot)")}
    if cols and "news" not in cols:
        conn.execute("ALTER TABLE player_snapshot ADD COLUMN news TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(player)")}
    for name in ("first_name", "second_name"):
        if cols and name not in cols:
            conn.execute(f"ALTER TABLE player ADD COLUMN {name} TEXT")


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


def refresh_xp_cache(conn):
    """Replace xp_next_cache with the current rows of v_xp_next (run after every data load)."""
    conn.execute("CREATE TABLE IF NOT EXISTS xp_next_cache (player_id INTEGER PRIMARY KEY, "
                 "xp_next REAL, xp_next3 REAL, start_prob REAL, xp_source TEXT)")
    conn.execute("DELETE FROM xp_next_cache")
    conn.execute("INSERT INTO xp_next_cache SELECT player_id, xp_next, xp_next3, start_prob, xp_source "
                 "FROM v_xp_next")
    conn.commit()


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
    refresh_xp_cache(mem)
    return mem
