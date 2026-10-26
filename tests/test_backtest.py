import math

import pytest

from fpl import backtest

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
    # no FPL prediction: still scored by the archive methods, which don't need ep_pre
    conn.execute("INSERT INTO player_gw VALUES ('2026-27',6,4,2,90,12,1,4,3,NULL)")
    # bench warmer: 0 minutes and start_prob 0 -> not in a squad
    conn.execute("INSERT INTO player_gw VALUES ('2026-27',6,5,1,0,0,1,4,3,0.5)")
    conn.commit()


def test_backtest_same_rows_for_all_methods(db_with_sample):
    _sample_rows(db_with_sample, False)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    ns = {r[m]["n"] for m in backtest.METHODS}
    assert len(ns) == 1 and ns.pop() == 7          # 3 players x 2 gws + player 4 (no ep_pre)


def test_methods_are_ours_only():
    assert backtest.METHODS == ("model", "last5_avg", "v2")


def test_archive_tables_have_no_fpl_rows_and_dont_need_ep_pre(db_with_sample):
    conn = db_with_sample
    _three_gw_rows(conn, ep6=None)
    _sample_rows(conn, False)
    conn.execute("UPDATE player_gw SET ep_pre = NULL")
    r = backtest.run(conn, "2026-27", from_gw=6)
    assert "fpl_ep" not in r and "fpl_ep" not in r["three_gw"]
    assert {r[m]["n"] for m in backtest.METHODS} == {8}     # 7 from _sample_rows + gw 8
    assert r["covered_gws"] == [6, 7, 8]
    t = r["three_gw"]
    assert t["starts"] == [6] and {t[m]["n"] for m in backtest.METHODS} == {4}
    assert r["source_1gw"] in backtest.METHODS and r["source_3gw"] in backtest.METHODS


def test_backtest_sets_forecast_source_meta(db_with_sample):
    _sample_rows(db_with_sample, True)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert r["winner"] == r["source_1gw"] != "fpl_ep"
    assert _meta(db_with_sample, "forecast_source_1gw") == r["source_1gw"]
    assert _meta(db_with_sample, "forecast_source_3gw") == r["source_3gw"]
    assert _meta(db_with_sample, "forecast_source") == r["source_1gw"]   # compatibility: = 1gw


def test_report_contains_table(db_with_sample, tmp_path):
    db_with_sample.execute("INSERT INTO meta (key, value) VALUES ('fit_season', '2024-25')")
    _sample_rows(db_with_sample, False)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "r" / "backtest.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "| Method | MAE | Rows |" in text
    for m in backtest.METHODS:
        assert backtest.LABELS[m] in text
    assert "| FPL" not in text                      # no FPL row in the archive tables
    assert "fitted on 2024-25" in text and "same season" not in text


def _three_gw_rows(conn, ep6=5.0, ep7=None):
    """Player 1 (MID, team 1, one FDR-3 fixture in each of gws 6-8) scores 5, 4, 3.

    His last-5 average before gw 6 is 4.0 (4 points in gws 1-5).
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
    # last-5 average 4.0 x 3 fixtures = 12; actual 5 + 4 + 3 = 12
    assert t["last5_avg"]["mae"] == 0.0
    assert t["model"]["mae"] >= 0


def _meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def test_each_horizon_is_decided_by_its_own_table(db_with_sample):
    conn = db_with_sample
    _three_gw_rows(conn)
    # gw 7 scores 0: 3-GW actual = 8. v2 predicts 2 per gw (6 over 3), last-5 x 3 = 12,
    # model ~12: v2 wins the 3-GW table. 1-GW (gws 6-7): last-5's 4.0 vs 5 and 0.
    conn.execute("UPDATE player_gw SET total_points = 0 WHERE season='2026-27' AND gw = 7 AND player_id = 1")
    r = backtest.run(conn, "2026-27", from_gw=6)
    assert r["source_3gw"] == "v2"
    assert r["source_1gw"] == backtest.choose_source(r)
    assert _meta(conn, "forecast_source_3gw") == "v2"


def test_backtest_includes_v2_same_rows(db_with_sample):
    _three_gw_rows(db_with_sample)
    _sample_rows(db_with_sample, False)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    assert "v2" in backtest.METHODS
    assert len({r[m]["n"] for m in backtest.METHODS}) == 1 and r["v2"]["n"] > 0
    assert len({r["three_gw"][m]["n"] for m in backtest.METHODS}) == 1
    assert r["three_gw"]["v2"]["n"] > 0
    assert r["v2"]["mae"] == r["v2"]["mae"]            # not NaN


def _table(**maes):
    return {m: {"mae": v, "n": 10} for m, v in maes.items()}


def test_choose_source_lowest_mae_of_ours():
    assert backtest.choose_source(_table(model=1.2, last5_avg=1.3, v2=1.0)) == "v2"
    assert backtest.choose_source(_table(model=1.0, last5_avg=1.3, v2=1.1)) == "model"
    assert backtest.choose_source(_table(model=1.5, last5_avg=0.8, v2=0.9)) == "last5_avg"
    # ties go to the model, then v2
    assert backtest.choose_source(_table(model=1.0, last5_avg=1.0, v2=1.0)) == "model"
    assert backtest.choose_source(_table(model=1.2, last5_avg=1.0, v2=1.0)) == "v2"


def test_choose_source_never_fpl():
    t = _table(model=1.2, last5_avg=1.3, v2=1.1, fpl_ep=0.1)
    assert backtest.choose_source(t) in {"model", "v2", "last5_avg"}
    assert backtest.choose_source(t) == "v2"
    # a method with no rows can't win
    t = {"model": {"mae": 1.2, "n": 5}, "v2": {"mae": float("nan"), "n": 0},
         "last5_avg": {"mae": 1.3, "n": 5}}
    assert backtest.choose_source(t) == "model"


# --- leak check ---------------------------------------------------------------------------

# (gw, minutes, points) per player; gw 3 of player 902 is a double gameweek (two rows)
LEAK_PLAYERS = {
    901: [(1, 90, 2), (2, 90, 2), (3, 90, 2), (4, 90, 2), (5, 90, 14), (6, 90, 2),
          (7, 0, 0), (8, 90, 3)],
    902: [(1, 90, 1), (2, 90, 6), (3, 90, 1), (3, 90, 1), (4, 0, 0), (5, 90, 8),
          (6, 90, 3), (7, 90, 5)],
}


def _gw_points(rows):
    """{gw: (minutes, points)} summed over a double gameweek."""
    out = {}
    for gw, mins, pts in rows:
        m, p = out.get(gw, (0, 0))
        out[gw] = (m + mins, p + pts)
    return out


def _avg_played(by_gw, lo, hi):
    pts = [p for g, (m, p) in by_gw.items() if lo <= g <= hi and m > 0]
    return sum(pts) / len(pts) if pts else None


def _leak_rows(conn, season, leaked):
    """ep_pre = average over played gws g-3..g (leaked) or g-4..g-1 (clean)."""
    for pid, rows in LEAK_PLAYERS.items():
        by_gw = _gw_points(rows)
        for n, (gw, mins, pts) in enumerate(rows):
            ep = (_avg_played(by_gw, gw - 3, gw) if leaked
                  else _avg_played(by_gw, gw - 4, gw - 1))
            conn.execute("INSERT INTO player_gw VALUES (?,?,?,?,?,?,1,2,3,?)",
                         (season, gw, pid, 500 + n, mins, pts, ep))
    conn.commit()


def test_leak_check_detects_post_match_ep(tmp_db):
    _leak_rows(tmp_db, "2023-24", leaked=True)
    r = backtest.leak_check(tmp_db, "2023-24")
    assert set(r) == {"mae_incl", "mae_excl", "n", "big_ep_week", "big_ep_before", "n_big"}
    assert r["mae_incl"] == pytest.approx(0.0)
    assert r["mae_excl"] > r["mae_incl"]
    # scored: played, ep_pre present, and at least one played gw in g-4..g-1
    # player 901: gws 2-6 and 8 (6); player 902: gws 2, 3, 5, 6, 7 (5)
    assert r["n"] == 11
    # one 12+ score (901, gw 5): ep that week = (2+2+2+14)/4 = 5.0, the week before 2.0
    assert r["n_big"] == 1
    assert r["big_ep_week"] == pytest.approx(5.0) and r["big_ep_before"] == pytest.approx(2.0)
    assert r["big_ep_week"] > r["big_ep_before"]


def test_leak_check_clean_ep_shows_no_leak(tmp_db):
    _leak_rows(tmp_db, "2023-24", leaked=False)
    r = backtest.leak_check(tmp_db, "2023-24")
    assert r["mae_excl"] == pytest.approx(0.0)
    assert r["mae_excl"] < r["mae_incl"]
    assert r["big_ep_week"] == pytest.approx(r["big_ep_before"])


def test_leak_check_no_ep_pre(tmp_db):
    r = backtest.leak_check(tmp_db, "2023-24")
    assert r["n"] == 0 and r["n_big"] == 0 and math.isnan(r["mae_incl"])


# --- FPL's prediction, saved before kick-off (current season) -----------------------------

def _fair_rows(conn):
    """Current season gw 6 has FPL predictions (saved before the deadline); gw 7 has none."""
    for pid, fid, pts, ep in ((1, 11, 5, 4.5), (2, 11, 1, 1.0), (3, 12, 2, 2.5)):
        conn.execute("INSERT INTO player_gw VALUES ('2026-27',6,?,?,90,?,1,4,3,?)",
                     (pid, fid, pts, ep))
    conn.execute("INSERT INTO player_gw VALUES ('2026-27',7,1,13,90,3,1,4,3,NULL)")
    conn.commit()


def test_fpl_fair_check_too_early_under_5_gws(db_with_sample):
    _fair_rows(db_with_sample)
    r = backtest.fpl_fair_check(db_with_sample)
    assert r["verdict"] == "too early to call"
    assert r["gws"] == [6]
    assert set(r["methods"]) == {"fpl_ep", "v2", "model", "last5_avg"}
    assert {v["n"] for v in r["methods"].values()} == {3}
    assert r["methods"]["fpl_ep"]["mae"] == pytest.approx((0.5 + 0 + 0.5) / 3)
    assert r["players"] == 3


def test_fpl_fair_check_counts_excluded_gws(db_with_sample):
    _fair_rows(db_with_sample)
    r = backtest.fpl_fair_check(db_with_sample)
    assert r["excluded_gws"] == [1, 2, 3, 4, 5, 7]


def test_fpl_fair_check_nothing_saved(db_with_sample):
    r = backtest.fpl_fair_check(db_with_sample)
    assert r["gws"] == [] and r["verdict"] == "too early to call"
    assert r["excluded_gws"] == [1, 2, 3, 4, 5]
    assert {v["n"] for v in r["methods"].values()} == {0}


def test_fpl_fair_check_verdict_from_five_gws(db_with_sample, monkeypatch):
    _fair_rows(db_with_sample)
    maes = {"fpl_ep": 2.0, "v2": 1.5, "model": 1.8, "last5_avg": 1.9}

    def fake(conn, season, from_gw, with_fpl=False, n=5):
        out = {m: {"mae": v, "n": 10} for m, v in maes.items()}
        out.update(covered_gws=list(range(8, 8 + n)), players=4)
        return out
    for n, verdict in ((4, "too early to call"), (5, "v2")):
        monkeypatch.setattr(backtest, "_score_one_gw",
                            lambda c, s, f, with_fpl=False, n=n: fake(c, s, f, with_fpl, n))
        assert backtest.fpl_fair_check(db_with_sample)["verdict"] == verdict
    maes["fpl_ep"] = 1.0
    assert backtest.fpl_fair_check(db_with_sample)["verdict"] == "fpl_ep"


# --- report -------------------------------------------------------------------------------

def _full_result(conn):
    conn.execute("INSERT INTO meta (key, value) VALUES ('fit_season', '2024-25')")
    _three_gw_rows(conn, ep6=None)
    r = backtest.run(conn, "2026-27", from_gw=6)
    _leak_rows(conn, "2023-24", leaked=True)
    r["leak"] = {"2023-24": backtest.leak_check(conn, "2023-24")}
    # gw 6 gets FPL predictions saved before kick-off; gws 1-5, 7 and 8 have none
    conn.execute("INSERT INTO player_gw VALUES ('2026-27',6,2,11,90,1,1,4,3,1.0)")
    conn.execute("UPDATE player_gw SET ep_pre = 4.5 WHERE season='2026-27' AND gw=6 AND player_id=1")
    r["fair"] = backtest.fpl_fair_check(conn)
    return r


def test_report_has_leak_and_fair_sections(db_with_sample, tmp_path):
    r = _full_result(db_with_sample)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "## Leak check" in text
    assert "## FPL's prediction, saved before kick-off" in text
    assert "Current season check" not in text and "Pending until" not in text
    leak = r["leak"]["2023-24"]
    assert f"{leak['mae_incl']:.3f}" in text and f"{leak['mae_excl']:.3f}" in text
    assert f"{leak['big_ep_week']:.2f}" in text and f"{leak['big_ep_before']:.2f}" in text
    fair = r["fair"]
    assert "too early to call" in text
    assert backtest.LABELS["fpl_ep"] in text
    assert f"{fair['methods']['fpl_ep']['mae']:.3f}" in text
    assert "Gameweeks left out" in text and "1-5, 7-8" in text


def test_report_explains_rows_no_longer_need_ep_pre(db_with_sample, tmp_path):
    r = _full_result(db_with_sample)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "no longer need" in text
    assert "1.880 to 1.876" not in text       # old drift note no longer applies
    assert "Next gameweek:" in text and "Next 3 gameweeks:" in text
    assert "fitted on the 2024-25 season only" in text
    assert LABEL_V2 in text


def test_report_without_leak_or_fair(db_with_sample, tmp_path):
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)                     # no "leak" / "fair" keys
    text = p.read_text()
    assert "## Leak check" in text and "## FPL's prediction, saved before kick-off" in text


def test_report_has_three_gw_table(db_with_sample, tmp_path):
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "## 3-gameweek check" in text
    assert text.count("| Method | MAE | Rows |") == 2      # no fair table without r["fair"]
    assert "Start gameweeks (1): 6. Rows scored: 1 per method." in text
    assert "| Last-5 average × fixtures | 0.000 | 1 |" in text
    assert "separately" in text


def test_report_caveat_names_fit_season(db_with_sample, tmp_path):
    db_with_sample.execute("INSERT INTO meta (key, value) VALUES ('fit_season', '2024-25')")
    _three_gw_rows(db_with_sample)
    r = backtest.run(db_with_sample, "2026-27", from_gw=6)
    p = tmp_path / "b.md"
    backtest.write_report(r, p)
    text = p.read_text()
    assert "both fitted on 2024-25 and are scored here on 2026-27" in text
    assert "both results are out of sample" in text
