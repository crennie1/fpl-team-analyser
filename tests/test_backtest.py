from pathlib import Path

import pytest

from fpl import backtest
from fpl import db as db_

LABEL_V2 = backtest.LABELS["v2"]


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
    r["source_3gw"] = "fpl_ep"        # this tiny sample has no 3-GW rows; force the wording case
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
    fixture_of = {6: 11, 7: 13, 8: 16}       # player 1's real team-1 fixtures in gws 6-8
    for gw, pts, ep in ((6, 5, ep6), (7, 4, ep7), (8, 3, None)):
        conn.execute("INSERT INTO player_gw VALUES ('2026-27',?,1,?,90,?,1,4,3,?)",
                     (gw, fixture_of[gw], pts, ep))
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


def _meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def test_each_horizon_is_decided_by_its_own_table(db_with_sample):
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    # 1-GW: FPL 5 vs 5 (perfect) -> fpl_ep. 3-GW: last-5 (12) is perfect, FPL's scaled 15 is not,
    # and last-5 is not an app source, so the model is the 3-GW source.
    assert r["fpl_ep"]["mae"] == 0.0
    assert r["three_gw"]["last5_avg"]["mae"] < r["three_gw"]["fpl_ep"]["mae"]
    assert (r["source_1gw"], r["source_3gw"]) == ("fpl_ep", "model")
    assert _meta(db_with_sample, "forecast_source_1gw") == "fpl_ep"
    assert _meta(db_with_sample, "forecast_source_3gw") == "model"
    assert _meta(db_with_sample, "forecast_source") == "fpl_ep"    # compatibility: = 1gw


def test_backtest_includes_v2_same_rows(db_with_sample):
    _three_gw_rows(db_with_sample)
    _sample_rows(db_with_sample, False)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert len(backtest.METHODS) == 4 and "v2" in backtest.METHODS
    assert len({r[m]["n"] for m in backtest.METHODS}) == 1 and r["v2"]["n"] > 0
    assert len({r["three_gw"][m]["n"] for m in backtest.METHODS}) == 1
    assert r["three_gw"]["v2"]["n"] > 0
    assert r["v2"]["mae"] == r["v2"]["mae"]            # not NaN


def _table(**maes):
    return {m: {"mae": v, "n": 10} for m, v in maes.items()}


def test_v2_chosen_only_if_strictly_better():
    base = dict(model=1.2, last5_avg=1.3, fpl_ep=1.0)
    assert backtest.choose_source(_table(**base, v2=1.0)) == "fpl_ep"      # tie: fpl_ep stays
    assert backtest.choose_source(_table(**base, v2=1.2)) == "fpl_ep"
    assert backtest.choose_source(_table(**base, v2=0.99)) == "v2"
    # v2 beats FPL but not last-5: not strictly better than every method -> not v2
    assert backtest.choose_source(_table(model=1.5, last5_avg=0.8, fpl_ep=1.0, v2=0.9)) == "model"
    # tie with the model while FPL is worse: model stays
    assert backtest.choose_source(_table(model=1.0, last5_avg=1.3, fpl_ep=1.1, v2=1.0)) == "model"


def test_per_horizon_sources(db_with_sample):
    conn = db_with_sample
    _three_gw_rows(conn)
    # gw 7 scores 0: 3-GW actual = 8. v2 predicts 3 per gw (9 over 3), last-5 x 3 = 12,
    # FPL scaled = 15, model ~12: v2 wins the 3-GW table. 1-GW: FPL's 5 is perfect.
    conn.execute("UPDATE player_gw SET total_points = 0 WHERE season='2026-27' AND gw = 7 AND player_id = 1")
    r = backtest.run(conn, "2026-27", from_gw=6)
    assert (r["source_1gw"], r["source_3gw"]) == ("fpl_ep", "v2")
    db_.apply_views(conn)
    db_.refresh_xp_cache(conn)
    x = conn.execute("SELECT * FROM v_xp_next WHERE player_id = 1").fetchone()
    assert x["xp_source"] == "fpl_ep/v2"
    assert x["xp_next"] == pytest.approx(5.5)           # FPL ep_next for the coming gameweek
    assert x["xp_next3"] == pytest.approx(9.0)          # v2: 3.0 in each of gws 6-8
    c = conn.execute("SELECT xp_source, xp_next3 FROM xp_next_cache WHERE player_id = 1").fetchone()
    assert (c["xp_source"], c["xp_next3"]) == ("fpl_ep/v2", pytest.approx(9.0))


def test_current_season_check_pending(db_with_sample, tmp_path):
    _three_gw_rows(db_with_sample)
    assert backtest.current_season_check(db_with_sample) is None     # < 5 gameweeks with ep_pre
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)                                      # no "current_season" key
    assert "Pending until enough gameweeks (about GW12)" in p.read_text()


def test_current_season_check_needs_five_gameweeks(db_with_sample, monkeypatch):
    def fake(conn, season, from_gw, n):
        return {"season": season, "covered_gws": list(range(8, 8 + n))}
    for n, expect_none in ((4, True), (5, False)):
        monkeypatch.setattr(backtest, "_score_one_gw", lambda c, s, f, n=n: fake(c, s, f, n))
        assert (backtest.current_season_check(db_with_sample) is None) is expect_none


def test_report_shows_current_season_table_and_sources(db_with_sample, tmp_path):
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    r["current_season"] = dict(r, covered_gws=[8, 9, 10, 11, 12])
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "Pending" not in text and "gameweeks 8-12" in text
    assert "Next gameweek:" in text and "Next 3 gameweeks:" in text
    assert "fitted on the 2024-25 season only" in text
    assert LABEL_V2 in text


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
    assert "separately" in text and "strictly lower" in text
