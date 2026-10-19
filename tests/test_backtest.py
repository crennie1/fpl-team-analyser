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
