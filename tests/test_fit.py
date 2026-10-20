"""Tests for fpl.fit (calib_att = actual / predicted attacking points) and its CLI wiring."""
import pytest

from fpl import fit
from tests.test_forecast_v2 import CUR, add_player, add_stat_row, refresh, v2db  # noqa: F401


def _mid_pair(conn, goals_gw6=1, assists_gw6=1):
    """Two MIDs (one per team, so both opponent ratios are 1.0), each with xg 1.4 / xa 1.0 per
    90 in gws 1-5. Predicted attacking points for gw 6 are 1.4 x 5 + 1.0 x 3 = 10 each."""
    for pid, team in ((1, 1), (2, 2)):
        add_player(conn, pid, "MID", team)
        for gw in range(1, 7):
            add_stat_row(conn, gw, pid, team, xg=1.4, xa=1.0)
        conn.execute("UPDATE player_gw_stats SET goals = ?, assists = ? "
                     "WHERE season = ? AND player_id = ? AND gw = 6",
                     (goals_gw6, assists_gw6, CUR, pid))
    conn.execute("UPDATE meta SET value = ? WHERE key = 'fit_season'", (CUR,))
    refresh(conn)


def test_fit_ratio_per_position(v2db, monkeypatch):
    monkeypatch.setattr(fit, "MIN_PRED_POINTS", 1.0)    # tiny fixture; V5 threshold tested below
    _mid_pair(v2db)       # predicted 10 per player; actual 1 goal x 5 + 1 assist x 3 = 8
    pred = v2db.execute(
        "SELECT SUM(att_pred) FROM v_xp2_fixture WHERE season = ? AND as_of_gw = 6 AND gw = 6",
        (CUR,)).fetchone()[0]
    assert pred == pytest.approx(20.0)
    calib = fit.run(v2db)
    assert calib["MID"] == pytest.approx(0.8)
    stored = v2db.execute("SELECT value FROM model_param WHERE name = 'calib_att' "
                          "AND position = 'MID'").fetchone()[0]
    assert stored == pytest.approx(0.8)


def test_fit_zero_denominator_keeps_1(v2db, monkeypatch):
    monkeypatch.setattr(fit, "MIN_PRED_POINTS", 1.0)
    _mid_pair(v2db)
    calib = fit.run(v2db)
    for pos in ("GK", "DEF", "FWD"):          # nothing predicted for these positions
        assert calib[pos] == 1.0
    rows = {r["position"]: r["value"] for r in v2db.execute(
        "SELECT position, value FROM model_param WHERE name = 'calib_att'")}
    assert rows["FWD"] == 1.0 and rows["MID"] == pytest.approx(0.8)


def test_fit_changes_the_forecast_and_is_idempotent(v2db, monkeypatch):
    monkeypatch.setattr(fit, "MIN_PRED_POINTS", 1.0)
    _mid_pair(v2db)
    def xp():
        return v2db.execute("SELECT xp_v2 FROM v_xp2 WHERE season = ? AND player_id = 1 "
                            "AND as_of_gw = 6 AND gw = 6", (CUR,)).fetchone()[0]
    before = xp()
    fit.run(v2db)
    fit.run(v2db)                              # second fit sees calib != 1 but must give the same
    assert fit.run(v2db)["MID"] == pytest.approx(0.8)
    assert xp() == pytest.approx(before - 0.2 * 10)    # attacking part scaled by 0.8


def test_fit_needs_50_predicted_points(v2db):
    _mid_pair(v2db)                      # MID predicts only 20 points in total
    assert fit.run(v2db)["MID"] == 1.0   # < 50: not fitted (V5)
    rows = {r["position"]: r["value"] for r in v2db.execute(
        "SELECT position, value FROM model_param WHERE name = 'calib_att'")}
    assert rows["MID"] == 1.0


def test_fit_clamps_to_0_5_and_2(v2db, monkeypatch):
    monkeypatch.setattr(fit, "MIN_PRED_POINTS", 1.0)
    _mid_pair(v2db, goals_gw6=0, assists_gw6=0)       # actual 0 / predicted 20 -> clamp up
    assert fit.run(v2db)["MID"] == 0.5
    v2db.execute("UPDATE player_gw_stats SET goals = 10 WHERE gw = 6")   # 100 / 20 = 5 -> clamp down
    assert fit.run(v2db)["MID"] == 2.0


def test_fit_gk_goal_worth_10(v2db, monkeypatch):
    """Actual GK attacking points use 10 per goal, the same GOAL_PTS as the forecast."""
    monkeypatch.setattr(fit, "MIN_PRED_POINTS", 1.0)
    for pid, team in ((1, 1), (2, 2)):
        add_player(v2db, pid, "GK", team)
        for gw in range(1, 7):
            add_stat_row(v2db, gw, pid, team, xg=0.8)      # predicted gw 6: 0.8 x 10 = 8 each
    v2db.execute("UPDATE player_gw_stats SET goals = 1 WHERE player_id = 1 AND gw = 6")
    v2db.execute("UPDATE meta SET value = ? WHERE key = 'fit_season'", (CUR,))
    refresh(v2db)
    assert fit.run(v2db)["GK"] == pytest.approx(10 / 16)
