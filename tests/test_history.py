from pathlib import Path

from fpl import history

FIX = Path(__file__).parent / "fixtures"


def _load(conn, season="2025-26"):
    return history.load(
        conn, season,
        FIX / "vaastav_merged_gw.csv", FIX / "vaastav_fixtures.csv", FIX / "vaastav_teams.csv",
    )


def test_history_maps_positions(tmp_db):
    _load(tmp_db)
    got = dict(tmp_db.execute("SELECT player_id, position FROM player").fetchall())
    assert got == {502: "GK", 541: "DEF", 612: "MID", 310: "FWD", 817: "FWD"}
    assert history.POSITIONS["GKP"] == "GK"


def test_history_ep_pre_from_xP(tmp_db):
    _load(tmp_db)
    ep = tmp_db.execute(
        "SELECT ep_pre FROM player_gw WHERE player_id = 612 AND gw = 1"
    ).fetchone()[0]
    assert ep == 2.6


def test_history_fdr_from_fixtures(tmp_db):
    _load(tmp_db)
    away = tmp_db.execute(  # West Ham away at Sunderland: team_a_difficulty
        "SELECT fdr FROM player_gw WHERE player_id = 612 AND fixture_id = 5"
    ).fetchone()[0]
    home = tmp_db.execute(  # Sunderland at home: team_h_difficulty
        "SELECT fdr FROM player_gw WHERE player_id = 541 AND fixture_id = 5"
    ).fetchone()[0]
    assert (away, home) == (3, 2)


def test_history_double_gw_two_rows(tmp_db):
    n = _load(tmp_db)
    rows = tmp_db.execute(
        "SELECT fixture_id, was_home, fdr FROM player_gw"
        " WHERE player_id = 817 AND gw = 26 ORDER BY fixture_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(257, 0, 3), (310, 1, 4)]
    assert n == 6


def test_history_records_season_and_is_rerunnable(tmp_db):
    _load(tmp_db)
    _load(tmp_db)
    assert tmp_db.execute(
        "SELECT value FROM meta WHERE key = 'backtest_season'"
    ).fetchone()[0] == "2025-26"
    assert tmp_db.execute("SELECT COUNT(*) FROM player_gw").fetchone()[0] == 6


def test_history_all_zero_xP_gameweek_is_null(tmp_db, tmp_path):
    lines = (FIX / "vaastav_merged_gw.csv").read_text().splitlines()
    hdr = lines[0].split(",")
    base = dict(zip(hdr, lines[1].split(",")))

    def row(gw, xp, el):
        d = dict(base, GW=str(gw), xP=str(xp), element=str(el))
        return ",".join(d[h] for h in hdr)
    # gw 20: all zero (missing); gw 21: one zero, one real (populated)
    extra = [row(20, "0.0", 612), row(20, "0.0", 541), row(21, "0.0", 612), row(21, "3.1", 541)]
    p = tmp_path / "merged.csv"
    p.write_text("\n".join(lines + extra) + "\n")
    history.load(tmp_db, "2025-26", p, FIX / "vaastav_fixtures.csv", FIX / "vaastav_teams.csv")
    q = "SELECT ep_pre FROM player_gw WHERE gw = ? AND player_id = ?"
    assert tmp_db.execute(q, (20, 612)).fetchone()[0] is None
    assert tmp_db.execute(q, (20, 541)).fetchone()[0] is None
    assert tmp_db.execute(q, (21, 612)).fetchone()[0] == 0.0
    assert tmp_db.execute(q, (21, 541)).fetchone()[0] == 3.1


def _csv(tmp_path, rows, extra_cols):
    lines = (FIX / "vaastav_merged_gw.csv").read_text().splitlines()
    hdr = lines[0].split(",")
    base = dict(zip(hdr, lines[1].split(",")))
    out = [",".join(hdr + list(extra_cols))]
    for r in rows:
        d = dict(base, **r)
        out.append(",".join([d[h] for h in hdr] + [str(d.get(c, "")) for c in extra_cols]))
    p = tmp_path / "m.csv"
    p.write_text("\n".join(out) + "\n")
    return p


COLS = ("expected_goals", "expected_assists", "expected_goal_involvements",
        "expected_goals_conceded", "goals_scored", "assists", "clean_sheets",
        "goals_conceded", "starts", "defensive_contribution")


def _row(el, pos, dc, gw=1, fixture=5, xg="0.2", minutes=90):
    return dict(element=str(el), position=pos, GW=str(gw), fixture=str(fixture), xP="1.0",
                minutes=str(minutes), expected_goals=xg, expected_assists="0.1",
                expected_goal_involvements="0.3", expected_goals_conceded="1.5", goals_scored="1",
                assists="0", clean_sheets="0", goals_conceded="2", starts="1",
                defensive_contribution=str(dc))


def _load_csv(conn, path, season="2025-26"):
    return history.load(conn, season, path, FIX / "vaastav_fixtures.csv", FIX / "vaastav_teams.csv")


def test_history_stats_and_defcon_threshold(tmp_db, tmp_path):
    rows = [_row(541, "DEF", 10), _row(541, "DEF", 9, gw=2, fixture=6),
            _row(612, "MID", 11), _row(612, "MID", 12, gw=2, fixture=6),
            _row(310, "FWD", 12), _row(502, "GKP", 30)]
    _load_csv(tmp_db, _csv(tmp_path, rows, COLS))
    q = "SELECT defcon_actions, defcon_hits FROM player_gw_stats WHERE player_id=? AND gw=?"
    assert tuple(tmp_db.execute(q, (541, 1)).fetchone()) == (10, 1)
    assert tuple(tmp_db.execute(q, (541, 2)).fetchone()) == (9, 0)
    assert tuple(tmp_db.execute(q, (612, 1)).fetchone()) == (11, 0)
    assert tuple(tmp_db.execute(q, (612, 2)).fetchone()) == (12, 1)
    assert tuple(tmp_db.execute(q, (310, 1)).fetchone()) == (12, 1)
    assert tuple(tmp_db.execute(q, (502, 1)).fetchone()) == (30, 0)   # GK never hits
    r = tmp_db.execute("SELECT * FROM player_gw_stats WHERE player_id=541 AND gw=1").fetchone()
    assert (r["xg"], r["xa"], r["xgi"], r["xgc"]) == (0.2, 0.1, 0.3, 1.5)
    assert (r["goals"], r["assists"], r["clean_sheets"], r["goals_conceded"], r["starts"]) == (1, 0, 0, 2, 1)


def test_history_double_gw_sums_stats(tmp_db, tmp_path):
    rows = [_row(817, "FWD", 12, gw=26, fixture=257, xg="0.4"),
            _row(817, "FWD", 3, gw=26, fixture=310, xg="0.35", minutes=30)]
    _load_csv(tmp_db, _csv(tmp_path, rows, COLS))
    r = tmp_db.execute("SELECT * FROM player_gw_stats WHERE player_id=817").fetchone()
    assert abs(r["xg"] - 0.75) < 1e-9 and r["apps"] == 2 and r["minutes"] == 120
    assert r["goals"] == 2 and r["defcon_actions"] == 15 and r["defcon_hits"] == 1
    assert tmp_db.execute("SELECT COUNT(*) FROM player_gw_stats").fetchone()[0] == 1


def test_history_no_defcon_column_null(tmp_db):
    _load(tmp_db)     # fixture CSV has no stats columns at all
    r = tmp_db.execute("SELECT * FROM player_gw_stats WHERE player_id = 541").fetchone()
    assert r["defcon_actions"] is None and r["defcon_hits"] is None
    assert r["xg"] is None and r["minutes"] == 90 and r["apps"] == 1


def test_history_sets_fit_and_backtest_season(tmp_db):
    def meta():
        return dict(tmp_db.execute("SELECT key, value FROM meta").fetchall())
    _load(tmp_db, "2024-25")
    assert meta()["backtest_season"] == "2024-25" and "fit_season" not in meta()
    _load(tmp_db, "2025-26")
    assert meta()["backtest_season"] == "2025-26" and meta()["fit_season"] == "2024-25"


def test_history_fit_and_backtest_season_either_order(tmp_db):
    _load(tmp_db, "2025-26")
    _load(tmp_db, "2024-25")
    m = dict(tmp_db.execute("SELECT key, value FROM meta").fetchall())
    assert (m["backtest_season"], m["fit_season"]) == ("2025-26", "2024-25")


def test_history_skips_manager_rows(tmp_db, tmp_path):
    rows = [_row(541, "DEF", 10), _row(9999, "AM", 0)]
    _load_csv(tmp_db, _csv(tmp_path, rows, COLS))
    assert tmp_db.execute("SELECT COUNT(*) FROM player WHERE player_id = 9999").fetchone()[0] == 0
    assert tmp_db.execute("SELECT COUNT(*) FROM player_gw WHERE player_id = 9999").fetchone()[0] == 0
