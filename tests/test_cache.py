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
    """refresh_xp_cache also snapshots the breakdown; it equals the live v_xp2_breakdown_next."""
    from fpl.db import refresh_xp_cache
    add_player(v2db, 1, "DEF", 1)
    add_player(v2db, 2, "MID", 2)
    for gw in range(1, 7):
        add_stat_row(v2db, gw, 1, 1, hits=1)
        add_stat_row(v2db, gw, 2, 2, xg=0.5)
    refresh(v2db)
    v2db.execute("CREATE TABLE xp2_breakdown_cache (player_id INTEGER PRIMARY KEY)")   # older shape
    refresh_xp_cache(v2db)
    view = [tuple(r) for r in v2db.execute("SELECT * FROM v_xp2_breakdown_next ORDER BY player_id")]
    cache = [tuple(r) for r in v2db.execute("SELECT * FROM xp2_breakdown_cache ORDER BY player_id")]
    assert cache == view and len(cache) == 2


@pytest.mark.parametrize("next_gw", ["7", "8", "9"])     # single, double (team 1), blank (team 1)
def test_cached_path_equals_live_v2(v2db, next_gw):
    """The refresh runs v2 once (xp2_fixture_next_cache); what it stores must equal the live views."""
    from fpl.db import refresh_xp_cache
    from tests.test_forecast_v2 import mirror_league
    mirror_league(v2db)
    v2db.execute("UPDATE meta SET value = ? WHERE key = 'next_gw'", (next_gw,))
    refresh_xp_cache(v2db)                                   # no forecast_source: v2 everywhere
    live = {r["player_id"]: r for r in v2db.execute("SELECT * FROM v_xp2_next")}
    assert len(live) == 2
    for r in v2db.execute("SELECT x.player_id, x.xp_next, x.xp_next3, x.xp_source, x.cs_display, "
                          "       b.total FROM xp_next_cache AS x "
                          "JOIN xp2_breakdown_cache AS b USING (player_id)"):
        v = live[r["player_id"]]
        assert r["xp_source"] == "v2"
        assert r["xp_next"] == v["xp_v2_next"] and r["total"] == v["xp_v2_next"]
        assert r["xp_next3"] == v["xp_v2_next3"] and r["cs_display"] == v["cs_display_next"]
    assert ([tuple(r) for r in v2db.execute("SELECT * FROM v_xp2_next_cached ORDER BY player_id")]
            == [tuple(r) for r in v2db.execute("SELECT * FROM v_xp2_next ORDER BY player_id")])
