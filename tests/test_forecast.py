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


def test_xp_next_respects_forecast_source(db_with_sample):
    conn = db_with_sample
    default = conn.execute("SELECT * FROM v_xp_next WHERE player_id=1").fetchone()
    assert default["xp_source"] == "model"
    assert default["xp_next"] == pytest.approx(4.0)           # start 1 x 4 pts/90 x mult 1
    # next 3 gws: team 1 plays once in each of gws 6, 7, 8
    assert default["xp_next3"] == pytest.approx(12.0)

    conn.execute("INSERT INTO meta (key, value) VALUES ('forecast_source', 'fpl_ep')")
    ep = conn.execute("SELECT * FROM v_xp_next WHERE player_id=1").fetchone()
    assert ep["xp_source"] == "fpl_ep"
    assert ep["xp_next"] == pytest.approx(5.5)                # snapshot ep_next
    assert ep["xp_next3"] == pytest.approx(12.0)              # always the model
    # player with no snapshot falls back to the model
    e = conn.execute("SELECT * FROM v_xp_next WHERE player_id=5").fetchone()
    assert e["xp_source"] == "model"
