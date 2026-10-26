import pytest


def form(conn, pid, as_of, season="2026-27"):
    return conn.execute(
        "SELECT * FROM v_player_form WHERE season=? AND player_id=? AND as_of_gw=?",
        (season, pid, as_of)).fetchone()


def xp(conn, pid, gw, as_of=6):
    return conn.execute(
        "SELECT xp_model FROM v_xp WHERE season='2026-27' AND player_id=? AND gw=? AND as_of_gw=?",
        (pid, gw, as_of)).fetchone()["xp_model"]


def test_start_prob_caps_at_1(db_with_sample):
    assert form(db_with_sample, 1, 6)["start_prob"] == pytest.approx(1.0)   # 5 x 90 min
    assert form(db_with_sample, 2, 6)["start_prob"] == pytest.approx(0.5)   # 5 x 45 min


def test_start_prob_uses_chance_next(db_with_sample):
    # C: 450 min -> 1.0, chance_next 25 -> 0.25 (as_of 6 is the upcoming gameweek)
    assert form(db_with_sample, 3, 6)["start_prob"] == pytest.approx(0.25)
    # chance only applies to the upcoming gameweek, not to earlier as_of values
    assert form(db_with_sample, 3, 5)["start_prob"] == pytest.approx(4 * 90 / 450)


def test_pts_per_90_uses_only_past(db_with_sample):
    # D scored 2 pts/90 in gws 1-3 and 12 pts/90 in gws 4-5
    assert form(db_with_sample, 4, 4)["pts_per_90"] == pytest.approx(2.0)      # gws 1-3 only
    assert form(db_with_sample, 4, 6)["pts_per_90"] == pytest.approx(30 / 5)   # gws 1-5


def test_xp_new_player_uses_position_default(db_with_sample):
    f = form(db_with_sample, 5, 6)                      # E: no minutes at all
    # MID average for 2026-27: (A 20 pts + B 5 pts) / (450 + 225 min) * 90
    assert f["pts_per_90"] == pytest.approx(25 * 90 / 675)
    assert f["start_prob"] == 0
    assert xp(db_with_sample, 5, 6) == 0                # zero, not NULL


def test_xp_blank_and_double(db_with_sample):
    # D (team 3): one fixture in gw 6, two in gw 7
    one = xp(db_with_sample, 4, 6)
    assert one == pytest.approx(1.0 * 6.0 * 1.0)        # start 1 x 6 pts/90 x mult 1
    assert xp(db_with_sample, 4, 7) == pytest.approx(2 * one)
    # C (team 2) blanks in gw 7: a row with 0, not a missing row
    assert xp(db_with_sample, 3, 7) == 0


def test_fdr_multiplier_mean_is_about_1(db_with_sample):
    rows = db_with_sample.execute("""
        SELECT m.position, SUM(g.minutes * m.mult) / SUM(g.minutes) AS weighted
        FROM player_gw g
        JOIN player p ON p.season = g.season AND p.player_id = g.player_id
        JOIN v_fdr_multiplier m ON m.position = p.position AND m.fdr = g.fdr
        WHERE g.season = '2025-26'
        GROUP BY m.position""").fetchall()
    assert {r["position"] for r in rows} == {"MID", "DEF", "FWD"}
    for r in rows:
        assert r["weighted"] == pytest.approx(1.0, abs=0.05)
    mid = {r["fdr"]: r["mult"] for r in db_with_sample.execute(
        "SELECT fdr, mult FROM v_fdr_multiplier WHERE position='MID'")}
    assert mid == pytest.approx({2: 1.5, 3: 1.0, 4: 0.5})


def _use_model(conn):
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source', 'model')")


def test_xp_next_respects_forecast_source(db_with_sample):
    conn = db_with_sample
    _use_model(conn)
    default = conn.execute("SELECT * FROM v_xp_next WHERE player_id=1").fetchone()
    assert default["xp_source"] == "model"
    assert default["xp_next"] == pytest.approx(4.0)           # start 1 x 4 pts/90 x mult 1
    # next 3 gws: team 1 plays once in each of gws 6, 7, 8
    assert default["xp_next3"] == pytest.approx(12.0)


def test_meta_fpl_ep_now_means_v2(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_1gw', 'fpl_ep')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_3gw', 'fpl_ep')")
    r = conn.execute("SELECT * FROM v_xp_next WHERE player_id=1").fetchone()
    v2 = conn.execute("SELECT * FROM v_xp2_next WHERE player_id = 1").fetchone()
    assert r["xp_source"] == "v2"
    assert r["xp_next"] == pytest.approx(v2["xp_v2_next"])
    assert r["xp_next3"] == pytest.approx(v2["xp_v2_next3"])


def test_old_single_fpl_ep_meta_means_v2(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source', 'fpl_ep')")
    assert conn.execute("SELECT xp_source FROM v_xp_next WHERE player_id=1").fetchone()[0] == "v2"


def test_player_without_v2_falls_back_to_model(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source', 'fpl_ep')")
    # stand-in v2 view (v_xp_next reads v_xp2_next_cached): player 1 has no v2 number, player 2 has one
    conn.execute("DROP VIEW v_xp2_next_cached")
    conn.execute("CREATE VIEW v_xp2_next_cached AS "
                 "SELECT 1 AS player_id, NULL AS xp_v2_next, NULL AS xp_v2_next3, "
                 "NULL AS defcon_chance_next, NULL AS cs_chance_next, NULL AS cs_display_next "
                 "UNION ALL SELECT 2, 3.0, 9.0, 0.1, 0.2, 0.2")
    r = _next(conn, 1)
    assert r["xp_source"] == "model"
    assert r["xp_next"] == pytest.approx(4.0)
    assert _next(conn, 2)["xp_source"] == "v2"


def test_xp_next_never_equals_ep_next_by_construction(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source', 'fpl_ep')")
    before = _next(conn)
    conn.execute("UPDATE player_snapshot SET ep_next = 99 WHERE player_id = 1")
    r = _next(conn)
    assert r["xp_next"] == pytest.approx(before["xp_next"])
    assert r["xp_next3"] == pytest.approx(before["xp_next3"])
    assert r["xp_next"] != pytest.approx(99)


def _last5(conn, pid=1):
    return [r[0] for r in conn.execute(
        "SELECT SUM(total_points) FROM player_gw WHERE season='2026-27' AND player_id=? "
        "AND gw < 6 GROUP BY gw ORDER BY gw DESC LIMIT 5", (pid,))]


def test_last5_avg_source_is_average_times_fixtures(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_1gw', 'last5_avg')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_3gw', 'last5_avg')")
    vals = _last5(conn)
    avg = sum(vals) / len(vals)
    r = _next(conn)
    assert r["xp_source"] == "last5_avg"
    assert r["xp_next"] == pytest.approx(avg)                 # one fixture in gw 6
    assert r["xp_next3"] == pytest.approx(3 * avg)            # one fixture in each of 6, 7, 8


def test_last5_avg_double_gw_and_blank(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_1gw', 'last5_avg')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_3gw', 'last5_avg')")
    avg = sum(_last5(conn)) / len(_last5(conn))
    conn.execute("INSERT INTO fixture (season, fixture_id, gw, team_h, team_a, team_h_difficulty, "
                 "team_a_difficulty, finished) VALUES ('2026-27', 900, 6, 1, 4, 4, 3, 0)")
    conn.execute("DELETE FROM fixture WHERE fixture_id=?", (_team1_fixture(conn, 8),))
    r = _next(conn)
    assert r["xp_next"] == pytest.approx(2 * avg)
    assert r["xp_next3"] == pytest.approx(3 * avg)            # 2 + 1 + 0


def test_last5_avg_without_history_falls_back_to_model(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_1gw', 'last5_avg')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_3gw', 'last5_avg')")
    conn.execute("DELETE FROM player_gw WHERE season='2026-27' AND player_id=1")
    r = _next(conn)
    assert r["xp_source"] == "model"


def test_in_progress_gameweek_not_counted_as_zero(db_with_sample):
    # gws 1-5 loaded, gw 6 not loaded (in progress / unplayed): as_of 7 looks back
    # from gw 5, so A (90 min in each loaded gw) still has start_prob 1.0.
    assert form(db_with_sample, 1, 7)["start_prob"] == pytest.approx(1.0)
    assert form(db_with_sample, 1, 8)["start_prob"] == pytest.approx(1.0)


def test_position_average_does_not_see_future(db_with_sample):
    conn = db_with_sample
    before = form(conn, 5, 5)["pts_per_90"]          # E's fallback, using gws 1-4
    # MID gws 1-4: A 16 pts + B 4 pts over 4*(90+45) min
    assert before == pytest.approx(20 * 90 / 540)
    conn.execute("UPDATE player_gw SET total_points = 100 WHERE season='2026-27' AND gw = 5")
    after = form(conn, 5, 5)["pts_per_90"]
    assert after == pytest.approx(before)            # gw 5 is not before as_of 5
    # ...but it does show up one gameweek later
    assert form(conn, 5, 6)["pts_per_90"] > before


def test_chance_next_scales_only_next_gw(db_with_sample):
    # C: 2 pts/90, start 1.0, chance_next 25. Fixtures in gw 6 and gw 8 (FDR 3, mult 1).
    assert xp(db_with_sample, 3, 6) == pytest.approx(0.25 * 2.0)   # next_gw: scaled
    assert xp(db_with_sample, 3, 8) == pytest.approx(2.0)          # next_gw + 2: unscaled


def _team1_fixture(conn, gw):
    return conn.execute("SELECT fixture_id FROM fixture WHERE season='2026-27' AND gw=? "
                        "AND team_h=1", (gw,)).fetchone()["fixture_id"]


def _next(conn, pid=1):
    return conn.execute("SELECT * FROM v_xp_next WHERE player_id=?", (pid,)).fetchone()


def test_xp_next3_model_source_unchanged(db_with_sample):
    conn = db_with_sample
    _use_model(conn)
    conn.execute("UPDATE fixture SET team_h_difficulty=2 WHERE fixture_id=?", (_team1_fixture(conn, 7),))
    r = _next(conn)
    assert r["xp_source"] == "model"
    assert r["xp_next3"] == pytest.approx(4.0 * (1.0 + 1.5 + 1.0))
    s = conn.execute("SELECT SUM(xp_model) AS s FROM v_xp WHERE season='2026-27' AND player_id=1 "
                     "AND as_of_gw=6 AND gw BETWEEN 6 AND 8").fetchone()["s"]
    assert r["xp_next3"] == pytest.approx(s)


# --- per-horizon sources (Task 3) ---

def test_xp_next_follows_each_horizon_source(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_1gw', 'model')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_3gw', 'v2')")
    r = _next(conn)
    v2 = conn.execute("SELECT * FROM v_xp2_next WHERE player_id = 1").fetchone()
    assert r["xp_source"] == "model/v2"
    assert r["xp_next"] == pytest.approx(4.0)                 # model
    assert r["xp_next3"] == pytest.approx(v2["xp_v2_next3"])


def test_v2_source_falls_back_to_model_without_v2_row(db_with_sample):
    conn = db_with_sample
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_1gw', 'v2')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source_3gw', 'v2')")
    r = _next(conn)
    v2 = conn.execute("SELECT * FROM v_xp2_next WHERE player_id = 1").fetchone()
    assert r["xp_source"] == "v2"
    assert r["xp_next"] == pytest.approx(v2["xp_v2_next"])
    assert r["xp_next3"] == pytest.approx(v2["xp_v2_next3"])
