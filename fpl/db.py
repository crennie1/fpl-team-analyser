"""SQLite helpers: connection, schema and SQL-file application."""
import math
import sqlite3
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"
VIEW_FILES = ("forecast.sql", "forecast_v2.sql", "squad.sql")


def _exp(x):
    return None if x is None else math.exp(x)


def _ln(x):
    """Like SQLite's ln: NULL for NULL and for x <= 0."""
    return None if x is None or x <= 0 else math.log(x)


def register_functions(conn, force=False):
    """Make sure `exp` and `ln` exist as SQL functions (forecast_v2.sql uses them).

    Most SQLite builds ship them (3.35+ with math functions); for any that is missing
    (`SELECT exp(0)` fails) we register Python versions that behave like SQLite's:
    NULL in, NULL out, and ln(x) is NULL for x <= 0. `force` registers them anyway (tests).
    """
    for name, expr, fn in (("exp", "exp(0)", _exp), ("ln", "ln(1)", _ln)):
        try:
            if force:
                raise sqlite3.OperationalError(name)
            conn.execute(f"SELECT {expr}").fetchone()
        except sqlite3.OperationalError:
            conn.create_function(name, 1, fn, deterministic=True)


def connect(path):
    conn = sqlite3.connect(str(path))
    register_functions(conn)
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
    """Apply forecast.sql, forecast_v2.sql, then squad.sql, skipping files that do not exist yet."""
    present = [f for f in VIEW_FILES if (SQL_DIR / f).exists()]
    if present:
        apply_sql(conn, *present)


def refresh_xp_cache(conn):
    """Replace xp_next_cache with the current rows of v_xp_next (run after every data load)."""
    # A cache, so it is safe to rebuild: this also upgrades an older committed db that
    # lacks the defcon_chance / cs_chance / cs_display columns.
    conn.execute("DROP TABLE IF EXISTS xp_next_cache")
    conn.execute("CREATE TABLE xp_next_cache (player_id INTEGER PRIMARY KEY, xp_next REAL, "
                 "xp_next3 REAL, start_prob REAL, xp_source TEXT, defcon_chance REAL, cs_chance REAL, "
                 "cs_display REAL)")
    conn.execute("INSERT INTO xp_next_cache SELECT player_id, xp_next, xp_next3, start_prob, "
                 "xp_source, defcon_chance, cs_chance, cs_display FROM v_xp_next")
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
    register_functions(mem)
    apply_sql(mem, "schema.sql")   # idempotent: adds tables a committed older db lacks (model_param)
    apply_views(mem)
    refresh_xp_cache(mem)
    return mem
