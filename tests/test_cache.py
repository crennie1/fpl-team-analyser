"""xp_next_cache: the snapshot of v_xp_next the app reads."""
import pytest

from tests.test_forecast_v2 import add_player, add_stat_row, refresh, v2db  # noqa: F401


def test_cache_has_defcon_and_cs(v2db):
    """xp_next_cache carries v2's descriptive DefCon and clean-sheet chances."""
    from fpl.db import refresh_xp_cache
    add_player(v2db, 1, "DEF", 1)
    add_player(v2db, 2, "MID", 2)
    for gw in range(1, 7):
        add_stat_row(v2db, gw, 1, 1, hits=1)
        add_stat_row(v2db, gw, 2, 2, xg=0.5)
    refresh(v2db)
    refresh_xp_cache(v2db)
    c = v2db.execute("SELECT * FROM xp_next_cache WHERE player_id = 1").fetchone()
    v = v2db.execute("SELECT * FROM v_xp2_next WHERE player_id = 1").fetchone()
    assert c["defcon_chance"] == pytest.approx(v["defcon_chance_next"]) and c["defcon_chance"] > 0
    assert c["cs_chance"] == pytest.approx(v["cs_chance_next"]) and 0 < c["cs_chance"] < 1


def test_cache_table_upgrades_in_place(v2db):
    """An older committed db has xp_next_cache without the new columns; refresh rebuilds it."""
    from fpl.db import refresh_xp_cache
    refresh(v2db)
    v2db.execute("DROP TABLE xp_next_cache")
    v2db.execute("CREATE TABLE xp_next_cache (player_id INTEGER PRIMARY KEY, xp_next REAL, "
                 "xp_next3 REAL, start_prob REAL, xp_source TEXT)")
    refresh_xp_cache(v2db)
    cols = {r[1] for r in v2db.execute("PRAGMA table_info(xp_next_cache)")}
    assert {"defcon_chance", "cs_chance"} <= cols


def test_breakdown_cache_copies_view(v2db):
    """refresh_xp_cache also snapshots v_xp2_breakdown_next; its total is the cached v2 number."""
    from fpl.db import refresh_xp_cache
    add_player(v2db, 1, "DEF", 1)
    add_player(v2db, 2, "MID", 2)
    for gw in range(1, 7):
        add_stat_row(v2db, gw, 1, 1, hits=1)
        add_stat_row(v2db, gw, 2, 2, xg=0.5)
    refresh(v2db)
    v2db.execute("DROP TABLE xp2_breakdown_cache")             # an older db without the table
    refresh_xp_cache(v2db)
    view = [tuple(r) for r in v2db.execute("SELECT * FROM v_xp2_breakdown_next ORDER BY player_id")]
    cache = [tuple(r) for r in v2db.execute("SELECT * FROM xp2_breakdown_cache ORDER BY player_id")]
    assert cache == view and len(cache) == 2
    for r in v2db.execute("SELECT b.total, x.xp_next FROM xp2_breakdown_cache AS b "
                          "JOIN xp_next_cache AS x USING (player_id)"):
        assert r["total"] == r["xp_next"]                       # source is v2 (no setting)
