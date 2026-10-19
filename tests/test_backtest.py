from pathlib import Path

from fpl import backtest


def _sample_rows(conn, ep_equals_actual):
    """Extend the 2026-27 sample so gw 6+ has played rows."""
    for gw in (6, 7):
        for pid, mins, pts in ((1, 90, 4), (2, 45, 1), (3, 90, 2)):
            pts = pts + (5 if gw == 7 else 0)   # vary so history baselines are imperfect
            ep = float(pts) if ep_equals_actual else 3.0
            conn.execute(
                "INSERT INTO player_gw VALUES ('2026-27',?,?,?,?,?,1,4,3,?)",
                (gw, pid, 1 if pid != 3 else 2, mins, pts, ep))
    # unrated row: ep_pre NULL -> excluded from every method
    conn.execute("INSERT INTO player_gw VALUES ('2026-27',6,4,2,90,12,1,4,3,NULL)")
    # bench warmer: 0 minutes and start_prob 0 -> not in a squad
    conn.execute("INSERT INTO player_gw VALUES ('2026-27',6,5,1,0,0,1,4,3,0.5)")
    conn.commit()


def test_backtest_same_rows_for_all_methods(db_with_sample):
    _sample_rows(db_with_sample, False)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    ns = {r[m]["n"] for m in backtest.METHODS}
    assert len(ns) == 1 and ns.pop() == 6


def test_backtest_perfect_predictor_mae_zero(db_with_sample):
    _sample_rows(db_with_sample, True)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert r["fpl_ep"]["mae"] == 0
    assert r["winner"] == "fpl_ep"


def test_backtest_sets_forecast_source(db_with_sample):
    _sample_rows(db_with_sample, True)
    backtest.run(db_with_sample, "2026-27", from_gw=6)
    src = db_with_sample.execute("SELECT value FROM meta WHERE key='forecast_source'").fetchone()[0]
    assert src == "fpl_ep"
    db_with_sample.execute("UPDATE player_gw SET ep_pre=100 WHERE ep_pre IS NOT NULL AND season='2026-27'")
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert r["winner"] != "fpl_ep"
    src = db_with_sample.execute("SELECT value FROM meta WHERE key='forecast_source'").fetchone()[0]
    assert src == "model"


def test_report_contains_table(db_with_sample, tmp_path):
    _sample_rows(db_with_sample, False)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "r" / "backtest.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "| Method | MAE | Rows |" in text
    for label in backtest.LABELS.values():
        assert label in text
    assert "fit" in text and "same season" in text


def test_backtest_excludes_null_ep_gameweek_for_all_methods(db_with_sample):
    _sample_rows(db_with_sample, False)
    db_with_sample.execute("UPDATE player_gw SET ep_pre = NULL WHERE season='2026-27' AND gw = 6")
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert {r[m]["n"] for m in backtest.METHODS} == {3}
    assert r["covered_gws"] == [7]


def test_report_fpl_ep_wording_matches_ruling_r20(db_with_sample, tmp_path):
    _sample_rows(db_with_sample, True)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert r["winner"] == "fpl_ep"
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "scaled by how many fixtures" in text
    assert "our model for the 3-gameweek" not in text


def _three_gw_rows(conn, ep6=5.0, ep7=None):
    """Player 1 (MID, team 1, one FDR-3 fixture in each of gws 6-8) scores 5, 4, 3.

    Every other player-gameweek in 6-8 has no FPL prediction, so only player 1
    is scored. His last-5 average before gw 6 is 4.0 (4 points in gws 1-5).
    """
    for gw, pts, ep in ((6, 5, ep6), (7, 4, ep7), (8, 3, None)):
        conn.execute("INSERT INTO player_gw VALUES ('2026-27',?,1,?,90,?,1,4,3,?)",
                     (gw, 100 + gw, pts, ep))
    conn.commit()


def test_three_gw_check_scores_each_method_on_identical_rows(db_with_sample):
    _three_gw_rows(db_with_sample, ep7=4.0)    # gw 7 is populated but 7+2 > last loaded gw 8
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    t = r["three_gw"]
    assert t["starts"] == [6]
    assert {t[m]["n"] for m in backtest.METHODS} == {1}
    # R20: ep_pre x (sum of multipliers gws 6-8) / (multiplier gw 6) = 5 x 3 = 15; actual 12
    assert t["fpl_ep"]["mae"] == 3.0
    # last-5 average 4.0 x 3 fixtures = 12
    assert t["last5_avg"]["mae"] == 0.0
    assert t["model"]["mae"] >= 0


def test_three_gw_check_does_not_pick_the_forecast(db_with_sample):
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    # 1-GW: FPL 5 vs 5 (perfect); 3-GW: last-5 is perfect. The 1-GW table decides.
    assert r["fpl_ep"]["mae"] == 0.0
    assert r["three_gw"]["last5_avg"]["mae"] < r["three_gw"]["fpl_ep"]["mae"]
    assert r["winner"] == "fpl_ep"
    src = db_with_sample.execute("SELECT value FROM meta WHERE key='forecast_source'").fetchone()[0]
    assert src == "fpl_ep"


def test_report_has_three_gw_table(db_with_sample, tmp_path):
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "## 3-gameweek check" in text
    assert text.count("| Method | MAE | Rows |") == 2
    assert "Start gameweeks (1): 6. Rows scored: 1 per method." in text
    assert "15.000" not in text and "| FPL ep_pre, scaled over 3 GWs (R20) | 3.000 | 1 |" in text
    assert "decided by the one-gameweek table" in text
