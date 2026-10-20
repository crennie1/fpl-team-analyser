"""Tests for the forecast v2 views (fpl/sql/forecast_v2.sql).

`v2db` is a tiny two-team league (team 1 v team 2 at home in every gameweek) so
every number can be checked by hand. Players are added with `add_stat_row`.
"""
import math

import pytest

from fpl import db
from tests.conftest import _insert

CUR = "2026-27"


@pytest.fixture
def v2db(tmp_db):
    conn = tmp_db
    _insert(conn, "meta", [
        {"key": "next_gw", "value": "7"}, {"key": "current_season", "value": CUR},
        {"key": "backtest_season", "value": "2025-26"}, {"key": "fit_season", "value": "2024-25"}])
    fixtures = [{"season": CUR, "fixture_id": gw, "gw": gw, "team_h": 1, "team_a": 2,
                 "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": int(gw <= 6)}
                for gw in range(1, 10) if gw != 9]
    # gw 8 is a double for team 1 (extra fixture away at team 3); gw 9: team 1 blanks
    fixtures.append({"season": CUR, "fixture_id": 108, "gw": 8, "team_h": 3, "team_a": 1,
                     "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": 0})
    fixtures.append({"season": CUR, "fixture_id": 109, "gw": 9, "team_h": 2, "team_a": 3,
                     "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": 0})
    _insert(conn, "fixture", fixtures)
    conn.commit()
    return conn


def add_player(conn, pid, position, team):
    _insert(conn, "player", [{"season": CUR, "player_id": pid, "web_name": f"P{pid}",
                              "team_id": team, "position": position}])


def add_stat_row(conn, gw, pid, team, minutes=90, pts=2, xg=0.0, xa=0.0, hits=0, apps=1,
                 fixture_id=None):
    """One player-fixture: team 1 is at home to team 2 (fixture id = gw) unless told otherwise."""
    fid = fixture_id or gw
    home = int(team == 1)
    _insert(conn, "player_gw", [{
        "season": CUR, "gw": gw, "player_id": pid, "fixture_id": fid, "minutes": minutes,
        "total_points": pts, "was_home": home, "opponent_team": 2 if team == 1 else 1,
        "fdr": 3, "ep_pre": None}])
    _insert(conn, "player_gw_stats", [{
        "season": CUR, "gw": gw, "player_id": pid, "minutes": minutes, "starts": int(minutes > 0),
        "xg": xg, "xa": xa, "xgi": xg + xa, "xgc": 0.0, "goals": 0, "assists": 0,
        "clean_sheets": 0, "goals_conceded": 0, "defcon_actions": 0, "defcon_hits": hits,
        "apps": apps}])


def refresh(conn):
    conn.commit()
    db.apply_views(conn)


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def test_team_conceded_by_position(v2db):
    add_player(v2db, 1, "MID", 1)
    add_player(v2db, 2, "MID", 2)
    add_stat_row(v2db, 3, 1, 1, pts=6)           # team 1's MID scores 6 then 2 against team 2
    add_stat_row(v2db, 4, 1, 1, pts=2)
    add_stat_row(v2db, 3, 2, 2, pts=0)
    add_stat_row(v2db, 4, 2, 2, pts=0)
    refresh(v2db)
    r = one(v2db, "SELECT * FROM v_team_conceded WHERE season=? AND team_id=2 AND position='MID' "
                  "AND as_of_gw=5", CUR)
    assert r["pts_pm"] == pytest.approx(4.0)     # (6 + 2) over 2 matches


def test_opp_weakness_ratio_vs_league(v2db):
    add_player(v2db, 1, "MID", 1)
    add_player(v2db, 2, "MID", 2)
    for gw, pts in ((3, 6), (4, 2)):
        add_stat_row(v2db, gw, 1, 1, pts=pts)
        add_stat_row(v2db, gw, 2, 2, pts=0)
    refresh(v2db)
    r = one(v2db, "SELECT * FROM v_opp_weakness WHERE season=? AND team_id=2 AND position='MID' "
                  "AND as_of_gw=5", CUR)
    assert r["pts_ratio"] == pytest.approx(2.0)   # team 2 concedes 4.0 v league average 2.0
    # no data at all -> neutral 1.0, never NULL
    g = one(v2db, "SELECT * FROM v_opp_weakness WHERE season=? AND team_id=2 AND position='GK' "
                  "AND as_of_gw=5", CUR)
    assert (g["pts_ratio"], g["xg_ratio"], g["defcon_ratio"]) == (1.0, 1.0, 1.0)


def defcon_league(conn, team1_hits, team2_hits, pos="DEF", pid=10):
    """Player `pid` (team 1) and a team-2 teammate-of-position over gws 1-6, one app a gameweek."""
    add_player(conn, pid, pos, 1)
    add_player(conn, pid + 1, pos, 2)
    for gw in range(1, 7):
        add_stat_row(conn, gw, pid, 1, hits=1 if gw <= team1_hits else 0)
        add_stat_row(conn, gw, pid + 1, 2, hits=1 if gw <= team2_hits else 0)
    refresh(conn)


def defcon(conn, pid=10, gw=7, as_of=7):
    return one(conn, "SELECT defcon_chance FROM v_defcon_chance WHERE season=? AND player_id=? "
                     "AND gw=? AND as_of_gw=?", CUR, pid, gw, as_of)["defcon_chance"]


def test_defcon_rate_and_chance(v2db):
    # player 10 hit 3 of 6. Team 2 concedes 0.5 hits a match to DEFs, team 1
    # concedes 2/6 -> league average 5/12 -> team 2's defcon_ratio = 1.2 -> chance 0.6
    defcon_league(v2db, 3, 2)
    t = one(v2db, "SELECT * FROM v_player_threat WHERE season=? AND player_id=10 AND as_of_gw=7", CUR)
    # shrunk toward the DEF average (5 hits in 12 apps): (3 + 3 x 5/12) / (6 + 3)
    rate = (3 + 3 * 5 / 12) / 9
    assert t["defcon_rate"] == pytest.approx(rate)
    assert one(v2db, "SELECT defcon_ratio FROM v_opp_weakness WHERE season=? AND team_id=2 "
                     "AND position='DEF' AND as_of_gw=7", CUR)[0] == pytest.approx(1.2)
    assert defcon(v2db) == pytest.approx(rate * 1.2)


def test_defcon_few_apps_shrunk(v2db):
    add_player(v2db, 10, "DEF", 1)
    add_player(v2db, 11, "DEF", 2)
    for gw in range(1, 7):
        add_stat_row(v2db, gw, 11, 2, hits=1 if gw <= 2 else 0)        # 2 hits in 6 apps
    for gw in (5, 6):
        add_stat_row(v2db, gw, 10, 1, hits=1)                          # 2 hits in 2 apps
    add_player(v2db, 12, "DEF", 1)                                     # team 1's other games
    for gw in range(1, 5):
        add_stat_row(v2db, gw, 12, 1)
    refresh(v2db)
    rate = one(v2db, "SELECT defcon_rate FROM v_player_threat WHERE season=? AND player_id=10 "
                     "AND as_of_gw=7", CUR)["defcon_rate"]
    assert rate == pytest.approx((2 + 3 * 4 / 12) / 5)                 # 0.6, not 1.0
    assert defcon(v2db) == pytest.approx(0.6)                          # opponent ratio 1.0


def test_opp_ratio_clamped(v2db):
    # four teams; only team 2 concedes MID points -> 10 v league mean 2.5 = 4.0 -> clamp 2.0;
    # team 1 concedes none -> 0 -> clamp 0.5
    add_player(v2db, 1, "MID", 1)
    add_player(v2db, 2, "MID", 2)
    add_stat_row(v2db, 3, 1, 1, pts=10)
    add_stat_row(v2db, 3, 2, 2, pts=0)
    _insert(v2db, "fixture", [{"season": CUR, "fixture_id": 203, "gw": 3, "team_h": 3, "team_a": 4,
                               "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": 1}])
    for pid, team, home in ((3, 3, 1), (4, 4, 0)):
        add_player(v2db, pid, "MID", team)
        _insert(v2db, "player_gw", [{"season": CUR, "gw": 3, "player_id": pid, "fixture_id": 203,
                                     "minutes": 90, "total_points": 0, "was_home": home,
                                     "opponent_team": 4 if team == 3 else 3, "fdr": 3,
                                     "ep_pre": None}])
    refresh(v2db)
    ratio = lambda team: one(v2db, "SELECT pts_ratio FROM v_opp_weakness WHERE season=? AND "
                                   "team_id=? AND position='MID' AND as_of_gw=5", CUR, team)[0]
    assert ratio(2) == 2.0 and ratio(1) == 0.5


def test_opp_ratio_tiny_league_average_is_neutral(v2db):
    add_player(v2db, 1, "MID", 1)
    add_player(v2db, 2, "MID", 2)
    for gw in (3, 4):
        add_stat_row(v2db, gw, 1, 1, xg=0.02)       # league mean xG conceded 0.01 a match < 0.05
        add_stat_row(v2db, gw, 2, 2, xg=0.0)
    refresh(v2db)
    r = one(v2db, "SELECT xg_ratio FROM v_opp_weakness WHERE season=? AND team_id=2 AND "
                  "position='MID' AND as_of_gw=5", CUR)
    assert r[0] == 1.0                               # unguarded this would be 2.0


def test_defcon_chance_capped(v2db):
    defcon_league(v2db, 6, 2)                     # rate 1.0 x ratio 1.5 -> capped
    assert defcon(v2db) == pytest.approx(0.95)


def test_defcon_gk_zero(v2db):
    defcon_league(v2db, 6, 2, pos="GK")
    t = one(v2db, "SELECT defcon_rate FROM v_player_threat WHERE season=? AND player_id=10 "
                  "AND as_of_gw=7", CUR)
    assert t["defcon_rate"] is None
    assert defcon(v2db) == 0


def test_cs_chance_exp(v2db):
    # each match both teams' forwards total 1.0 xG -> xGC per match 1.0, attack ratio 1.0
    add_player(v2db, 20, "DEF", 1)
    add_player(v2db, 21, "FWD", 1)
    add_player(v2db, 22, "FWD", 2)
    for gw in range(1, 7):
        add_stat_row(v2db, gw, 20, 1)
        add_stat_row(v2db, gw, 21, 1, xg=1.0)
        add_stat_row(v2db, gw, 22, 2, xg=1.0)
    refresh(v2db)
    r = one(v2db, "SELECT cs_chance FROM v_cs_chance WHERE season=? AND player_id=20 AND gw=7 "
                  "AND as_of_gw=7", CUR)
    assert r["cs_chance"] == pytest.approx(math.exp(-1), abs=1e-3)


def mirror_league(conn, pid=1):
    """Player `pid` (MID, team 1) and an identical MID (id+100) for team 2, gws 1-6:
    90 min, 0.3 xG, 0.15 xA, 4 pts, 2 DefCon hits in 6 apps. Mirrored, so all opponent ratios are 1.0."""
    add_player(conn, pid, "MID", 1)
    add_player(conn, pid + 100, "MID", 2)
    for gw in range(1, 7):
        for p, team in ((pid, 1), (pid + 100, 2)):
            add_stat_row(conn, gw, p, team, pts=4, xg=0.3, xa=0.15, hits=1 if gw <= 2 else 0)
    refresh(conn)


def xp_v2(conn, pid, gw, as_of=7):
    return one(conn, "SELECT xp_v2 FROM v_xp2 WHERE season=? AND player_id=? AND gw=? "
                     "AND as_of_gw=?", CUR, pid, gw, as_of)["xp_v2"]


HAND = 2 + (0.3 * 5 + 0.15 * 3) + math.exp(-0.3) + 2 * (2 / 6)   # appearance + att + CS + DefCon


def test_v2_components_sum(v2db):
    mirror_league(v2db)
    assert xp_v2(v2db, 1, 7) == pytest.approx(HAND)


def test_v2_uses_calibration(v2db):
    mirror_league(v2db)
    _insert(v2db, "model_param", [{"name": "calib_att", "position": "MID", "value": 0.5}])
    v2db.commit()
    assert xp_v2(v2db, 1, 7) == pytest.approx(HAND - 0.5 * (0.3 * 5 + 0.15 * 3))


def test_v2_blank_and_double(v2db):
    mirror_league(v2db)
    assert xp_v2(v2db, 1, 9) == 0                                  # team 1 blanks in gw 9
    assert xp_v2(v2db, 1, 8) == pytest.approx(2 * HAND)            # two identical-strength fixtures
    p = defcon(v2db, pid=1, gw=7)
    assert p == pytest.approx(1 / 3)
    assert defcon(v2db, pid=1, gw=8) == pytest.approx(1 - (1 - p) ** 2)
    assert defcon(v2db, pid=1, gw=9) == 0
    cs = lambda gw: one(v2db, "SELECT cs_chance FROM v_cs_chance WHERE season=? AND player_id=1 "
                              "AND gw=? AND as_of_gw=7", CUR, gw)["cs_chance"]
    assert cs(8) == pytest.approx(2 * math.exp(-0.3))              # double sums per fixture
    assert cs(9) == 0


def test_v2_new_player_not_null(v2db):
    mirror_league(v2db)
    add_player(v2db, 99, "MID", 1)                                 # no stats rows at all
    refresh(v2db)
    assert xp_v2(v2db, 99, 7) == 0                                 # start_prob 0, but a number
    assert defcon(v2db, pid=99) == 0
    cs = one(v2db, "SELECT cs_chance FROM v_cs_chance WHERE season=? AND player_id=99 AND gw=7 "
                   "AND as_of_gw=7", CUR)["cs_chance"]
    assert cs == pytest.approx(math.exp(-0.3))
    t = one(v2db, "SELECT xg90, xa90 FROM v_player_threat WHERE season=? AND player_id=99 "
                  "AND as_of_gw=7", CUR)
    assert t["xg90"] == pytest.approx(0.3) and t["xa90"] == pytest.approx(0.15)   # position average


def test_v2_no_lookahead(v2db):
    mirror_league(v2db)
    # make gameweek 6 only extreme; as_of 6 must not see it (it reads gws 1-5)
    before = one(v2db, "SELECT xg90, xa90, defcon_rate, team_xgc_pm FROM v_player_threat "
                       "WHERE season=? AND player_id=1 AND as_of_gw=6", CUR)
    before_c = one(v2db, "SELECT pts_pm, xg_pm FROM v_team_conceded WHERE season=? AND team_id=2 "
                         "AND position='MID' AND as_of_gw=6", CUR)
    v2db.execute("UPDATE player_gw_stats SET xg=9, xa=9, defcon_hits=1 WHERE gw>=6")
    v2db.execute("UPDATE player_gw SET total_points=50 WHERE gw>=6")
    refresh(v2db)
    after = one(v2db, "SELECT xg90, xa90, defcon_rate, team_xgc_pm FROM v_player_threat "
                      "WHERE season=? AND player_id=1 AND as_of_gw=6", CUR)
    after_c = one(v2db, "SELECT pts_pm, xg_pm FROM v_team_conceded WHERE season=? AND team_id=2 "
                        "AND position='MID' AND as_of_gw=6", CUR)
    assert tuple(before) == pytest.approx(tuple(after))
    assert tuple(before_c) == pytest.approx(tuple(after_c))


def test_xp2_next_view(v2db):
    mirror_league(v2db)                                            # next_gw is 7
    r = one(v2db, "SELECT * FROM v_xp2_next WHERE player_id=1")
    assert r["xp_v2_next"] == pytest.approx(HAND)
    assert r["xp_v2_next3"] == pytest.approx(HAND + 2 * HAND + 0)  # gw 7 + double gw 8 + blank gw 9
    assert r["defcon_chance_next"] == pytest.approx(1 / 3)
    assert r["cs_chance_next"] == pytest.approx(math.exp(-0.3))


def test_xp2_next_cs_display_in_double_gameweek(v2db):
    """cs_chance_next sums the fixtures (for xP); cs_display_next is P(at least one clean sheet)."""
    mirror_league(v2db)
    v2db.execute("UPDATE meta SET value = '8' WHERE key = 'next_gw'")   # team 1 has a double
    v2db.commit()
    r = one(v2db, "SELECT * FROM v_xp2_next WHERE player_id=1")
    p = math.exp(-0.3)
    assert r["cs_chance_next"] == pytest.approx(2 * p)
    assert r["cs_display_next"] == pytest.approx(1 - (1 - p) ** 2)


def test_gk_goal_worth_10(v2db):
    """FPL gives a goalkeeper's goal 10 points (GOAL_PTS GK 10, DEF 6)."""
    for pid, team in ((30, 1), (31, 2)):           # mirrored, so the opponent xG ratio is 1.0
        add_player(v2db, pid, "GK", team)
        for gw in range(1, 7):
            add_stat_row(v2db, gw, pid, team, xg=0.3)
    refresh(v2db)
    r = one(v2db, "SELECT att_pred FROM v_xp2_fixture WHERE season=? AND player_id=30 "
                  "AND as_of_gw=7 AND gw=7", CUR)
    assert r["att_pred"] == pytest.approx(0.3 * 10)


def test_no_stats_rows_give_no_phantom_clean_sheet(v2db):
    """Without player_gw_stats, xG is unknown (NULL), not 0, so clean-sheet chance is not 100%."""
    add_player(v2db, 1, "DEF", 1)
    add_player(v2db, 2, "DEF", 2)
    for gw in range(1, 7):
        for pid, team in ((1, 1), (2, 2)):
            add_stat_row(v2db, gw, pid, team)
    v2db.execute("DELETE FROM player_gw_stats")
    refresh(v2db)
    assert one(v2db, "SELECT xg FROM v_pf_stat WHERE season=? AND player_id=1 AND gw=3",
               CUR)["xg"] is None
    cs = one(v2db, "SELECT cs_chance FROM v_cs_chance WHERE season=? AND player_id=1 AND gw=7 "
                   "AND as_of_gw=7", CUR)["cs_chance"]
    assert cs is None or cs < 1.0
    xg = one(v2db, "SELECT xg_pm FROM v_team_conceded WHERE season=? AND team_id=2 "
                   "AND position='DEF' AND as_of_gw=7", CUR)["xg_pm"]
    assert xg is None


def test_fdr_multiplier_uses_fit_season(db_with_sample):
    conn = db_with_sample
    _insert(conn, "player", [{"season": "2024-25", "player_id": 201, "web_name": "Fit",
                              "team_id": 1, "position": "MID"}])
    _insert(conn, "player_gw", [
        {"season": "2024-25", "gw": n, "player_id": 201, "fixture_id": n, "minutes": 90,
         "total_points": pts, "was_home": 1, "opponent_team": 2, "fdr": fdr, "ep_pre": None}
        for n, (fdr, pts) in enumerate([(2, 10), (4, 5)], start=1)])
    _insert(conn, "meta", [{"key": "fit_season", "value": "2024-25"}])
    conn.commit()
    db.apply_views(conn)
    rows = {r["fdr"]: r for r in conn.execute(
        "SELECT * FROM v_fdr_multiplier WHERE position='MID'")}
    assert {r["season"] for r in rows.values()} == {"2024-25"}
    assert rows[2]["mult"] == pytest.approx(10 / 7.5) and rows[4]["mult"] == pytest.approx(5 / 7.5)


def test_exp_function_available(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    assert conn.execute("SELECT exp(1)").fetchone()[0] == pytest.approx(math.e)
    assert conn.execute("SELECT exp(NULL)").fetchone()[0] is None


def test_fallback_functions_match_sqlite(tmp_path):
    """Force the Python fallbacks on a fresh connection: NULL in -> NULL, ln(x <= 0) -> NULL."""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    db.register_functions(conn, force=True)
    q = lambda e: conn.execute(f"SELECT {e}").fetchone()[0]   # noqa: E731
    assert q("exp(0)") == 1.0 and q("exp(NULL)") is None
    assert q("ln(1)") == 0.0 and q("ln(NULL)") is None
    assert q("ln(0)") is None and q("ln(-2)") is None
    assert q("1.0 - exp(ln(1.0 - 0.25) + ln(1.0 - 0.5))") == pytest.approx(1 - 0.75 * 0.5)
